# SPDX-License-Identifier: AGPL-3.0-or-later
"""BLE-specific adapter ABCs: parser interface and Heart Rate Service adapter base.

``bleak`` is NOT imported at module level. The concrete lifecycle on
``BleHeartRateAdapter`` imports it lazily inside method bodies, guarded so a
missing or unavailable Bluetooth stack raises a clear ``RuntimeError`` rather
than a bare ``ImportError``. Concrete subclasses implement only ``matches`` and
``device_info``.
"""

from __future__ import annotations

import abc
import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any, ClassVar

from vitals_on_fhir.adapters.base import ConnectionState, DeviceAdapter
from vitals_on_fhir.vitals.base import DeviceInfo, VitalSign

if TYPE_CHECKING:
    # Imported only for type checkers; never at runtime (keeps the module
    # importable without a Bluetooth stack and keeps ``bleak`` out of the
    # module-level import graph the contract/dependency AST checks inspect).
    from datetime import datetime

logger = logging.getLogger(__name__)

#: GATT UUID of the Heart Rate Measurement characteristic (0x2A37).
HEART_RATE_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

#: GATT UUID of the Heart Rate Service (0x180D), used to filter advertisements.
HEART_RATE_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"

#: Reconnection backoff bounds (seconds).
_BACKOFF_INITIAL = 1.0
_BACKOFF_MAX = 30.0
_BACKOFF_FACTOR = 2.0

#: Sentinel pushed onto the queue to unblock ``vitals()`` on disconnect.
_DISCONNECT_SENTINEL = object()


class GattCharacteristicParser(abc.ABC):
    """Abstract parser for a single GATT characteristic notification payload.

    Implementations decode raw ``bytes`` from a BLE notification into a
    ``VitalSign`` domain object, returning ``None`` for malformed payloads so
    the adapter can drop them silently.
    """

    @abc.abstractmethod
    def parse(self, data: bytes) -> VitalSign | None:
        """Parse a raw GATT notification payload.

        Returns a ``VitalSign`` on success, or ``None`` if the payload is
        malformed and should be dropped.
        """
        ...


class BleHeartRateAdapter(DeviceAdapter, abc.ABC):
    """Abstract BLE adapter for the Bluetooth Heart Rate Service (GATT 0x180D).

    Provides a concrete connection lifecycle: BLE scanning, subscribing to
    characteristic 0x2A37, parsing via ``HeartRateMeasurementParser``, and a
    reconnection loop with capped exponential backoff. Concrete subclasses need
    only implement ``matches`` (advertisement filter) and the ``device_info``
    property.

    ``bleak`` is imported lazily inside method bodies; it is never imported at
    the module level here.
    """

    supported_vitals: ClassVar[tuple[type[VitalSign], ...]] = ()
    """Populated by the concrete subclass or set at class body level."""

    def __init__(
        self,
        *,
        device_name: str | None = None,
        on_state_change: Callable[[ConnectionState], Awaitable[None]] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize the BLE adapter lifecycle state.

        Args:
            device_name: Optional BLE advertised-name filter (``VOF_DEVICE_NAME``).
                When set, only advertisements whose name matches are considered,
                in addition to the subclass ``matches`` check.
            on_state_change: Optional async callback invoked on every connection
                state transition. Wired by ``cli.py`` to relay state to the
                dashboard broadcaster; the adapter itself never imports
                ``dashboard``.
            now: Optional clock returning a timezone-aware timestamp, forwarded
                to the parser so the reading's ``effective`` time is injectable
                for tests.
        """
        self._device_name = device_name
        self._on_state_change = on_state_change
        self._now = now
        self._state = ConnectionState.DISCONNECTED
        self._queue: asyncio.Queue[object] = asyncio.Queue()
        self._client: object | None = None
        self._closing = False
        self._parser: GattCharacteristicParser | None = None

    # -- Abstract members implemented by concrete subclasses ----------------

    @abc.abstractmethod
    def matches(self, advertisement: object) -> bool:
        """Return ``True`` if this adapter should handle the given advertisement.

        ``advertisement`` is a ``bleak.backends.device.BLEDevice`` at runtime;
        typed as ``object`` here to avoid a top-level ``bleak`` import.
        """
        ...

    @property
    @abc.abstractmethod
    def device_info(self) -> DeviceInfo:
        """Immutable description of the target device."""
        ...

    # -- Concrete lifecycle -------------------------------------------------

    @property
    def state(self) -> ConnectionState:
        """Current connection state (managed by the base implementation)."""
        return self._state

    async def connect(self) -> None:
        """Scan for the device, connect, and subscribe to heart-rate notifications.

        Imports ``bleak`` lazily. Sets ``CONNECTING`` while scanning and
        connecting, then ``CONNECTED`` once the notification subscription is in
        place. Exactly one device is connected per session (FR-1, FR-2).

        Raises:
            RuntimeError: if ``bleak`` (or the underlying Bluetooth stack) is
                unavailable, or if no matching device is found.
        """
        self._closing = False
        await self._set_state(ConnectionState.CONNECTING)
        try:
            await self._connect_once()
        except RuntimeError:
            raise
        except Exception as exc:  # pragma: no cover - hardware path
            raise RuntimeError(f"BLE connection failed: {exc}") from exc

    async def _connect_once(self) -> None:
        """Perform a single scan-connect-subscribe cycle. Imports ``bleak`` lazily."""
        bleak: Any = _import_bleak()

        device = await self._scan_for_device(bleak)
        if device is None:
            raise RuntimeError("no matching BLE heart-rate device found during scan")

        loop = asyncio.get_running_loop()
        client = bleak.BleakClient(device, disconnected_callback=self._on_disconnected)
        await client.connect()
        self._client = client
        logger.info("connected to BLE heart-rate device")

        def _notification_callback(_characteristic: object, data: bytearray) -> None:
            # Runs on bleak's thread: do no async work here. Hand the raw bytes
            # back to the event loop for parsing in ``vitals()``.
            loop.call_soon_threadsafe(self._queue.put_nowait, bytes(data))

        await client.start_notify(HEART_RATE_MEASUREMENT_UUID, _notification_callback)
        await self._set_state(ConnectionState.CONNECTED)

    async def _scan_for_device(self, bleak: Any) -> Any:
        """Scan for advertisements and return the first one that matches.

        A candidate matches when the subclass ``matches`` returns ``True`` and,
        if a ``device_name`` filter is configured, the advertised name matches.
        """
        scanner_cls = bleak.BleakScanner
        devices = await scanner_cls.discover(
            service_uuids=[HEART_RATE_SERVICE_UUID],
        )
        for device in devices:
            if self._device_name is not None:
                name = getattr(device, "name", None)
                if name != self._device_name:
                    continue
            if self.matches(device):
                return device
        return None

    def vitals(self) -> AsyncIterator[VitalSign]:
        """Yield ``HeartRate`` readings parsed from BLE notifications.

        Consumes the threadsafe queue the notification callback fills, parses
        each payload via ``HeartRateMeasurementParser``, drops malformed
        payloads (logged at ``DEBUG``), and yields well-formed ``HeartRate``
        objects indefinitely until ``disconnect`` is called. The generator
        stays alive across reconnects so downstream consumers resume
        automatically (FR-2, FR-6).
        """
        return self._vitals_iterator()

    async def _vitals_iterator(self) -> AsyncIterator[VitalSign]:
        """Async generator backing :meth:`vitals`."""
        parser = self._ensure_parser()
        while not self._closing:
            item = await self._queue.get()
            if item is _DISCONNECT_SENTINEL:
                break
            assert isinstance(item, bytes)
            vital = parser.parse(item)
            if vital is None:
                logger.debug("dropped malformed heart-rate payload (%d bytes)", len(item))
                continue
            yield vital

    def _ensure_parser(self) -> GattCharacteristicParser:
        """Return the parser, constructing it lazily from ``device_info``.

        The parser is imported lazily to respect the package dependency
        direction (``adapters.ble`` must not import ``adapters.parser`` at
        module load in a way that creates an import cycle, since ``parser``
        imports this module).
        """
        if self._parser is None:
            from vitals_on_fhir.adapters.parser import HeartRateMeasurementParser

            self._parser = HeartRateMeasurementParser(
                device_id=self._parser_device_id(),
                now=self._now,
            )
        return self._parser

    def _parser_device_id(self) -> str:
        """Return a stable device identifier for parsed readings.

        Prefers a Bluetooth address identifier when present, otherwise falls
        back to the model name.
        """
        info = self.device_info
        return info.identifiers.get("bluetooth_address", info.model)

    def _on_disconnected(self, _client: object) -> None:
        """``bleak`` disconnect callback: trigger a reconnection loop.

        Runs on bleak's thread. Schedules the reconnection coroutine on the
        event loop unless the adapter is intentionally closing.
        """
        if self._closing:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - no loop running
            return
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._reconnect_loop()))

    async def _reconnect_loop(self) -> None:
        """Retry ``connect`` with capped exponential backoff until it succeeds.

        Sets ``RECONNECTING`` and keeps retrying while the adapter is not
        closing. On success the state returns to ``CONNECTED`` and downstream
        consumption resumes without the ``vitals()`` generator restarting
        (NFR-2, FR-6).
        """
        if self._closing:
            return
        await self._set_state(ConnectionState.RECONNECTING)
        backoff = _BACKOFF_INITIAL
        while not self._closing:
            try:
                await self._connect_once()
            except Exception as exc:  # pragma: no cover - hardware path
                logger.info("reconnect attempt failed; retrying in %.1fs", backoff)
                logger.debug("reconnect error detail: %s", exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * _BACKOFF_FACTOR, _BACKOFF_MAX)
                continue
            else:
                logger.info("reconnected to BLE heart-rate device")
                return

    async def disconnect(self) -> None:
        """Stop notifications, disconnect, and unblock ``vitals()``.

        Sets the closing flag first so the reconnection loop and generator stop,
        stops notifications and disconnects the client if present, pushes the
        sentinel to unblock a waiting ``vitals()``, and sets ``DISCONNECTED``
        (FR-1, FR-6).
        """
        self._closing = True
        client = self._client
        if client is not None:
            try:
                await client.stop_notify(HEART_RATE_MEASUREMENT_UUID)  # type: ignore[attr-defined]
            except Exception as exc:  # pragma: no cover - hardware path
                logger.debug("error stopping notifications: %s", exc)
            try:
                await client.disconnect()  # type: ignore[attr-defined]
            except Exception as exc:  # pragma: no cover - hardware path
                logger.debug("error during disconnect: %s", exc)
            self._client = None
        self._queue.put_nowait(_DISCONNECT_SENTINEL)
        await self._set_state(ConnectionState.DISCONNECTED)
        logger.info("disconnected from BLE heart-rate device")

    async def _set_state(self, state: ConnectionState) -> None:
        """Update the connection state and invoke the injected state callback."""
        self._state = state
        if self._on_state_change is not None:
            await self._on_state_change(state)


def _import_bleak() -> object:
    """Import ``bleak`` lazily, raising a clear ``RuntimeError`` if unavailable.

    Keeping the import inside this function (never at module level) ensures the
    ``adapters`` package imports without a Bluetooth stack, so mock mode, the
    fast test suite, and CI work without ``bleak`` installed.
    """
    try:
        import bleak
    except ImportError as exc:
        raise RuntimeError(
            "bleak is required for BLE adapters but is not available; "
            "install the 'bleak' dependency and ensure a Bluetooth stack is present"
        ) from exc
    return bleak
