# SPDX-License-Identifier: AGPL-3.0-or-later
"""Concrete BLE adapter for the standard Bluetooth Weight Scale Service (GATT 0x181D).

``WeightScaleBleAdapter`` acquires body-weight readings from any device
implementing the standard Weight Scale Service (WSS) and its Weight Measurement
characteristic (``0x2A9D``). It reuses the shared
:class:`~vitals_on_fhir.adapters.BleConnection` lifecycle *by composition* —
scanning, connecting, subscribing (``bleak`` handles the characteristic's
indications transparently), and reconnecting are implemented once there — and
delegates payload decoding to ``WeightMeasurementParser``.

``bleak`` is imported lazily inside :class:`BleConnection`; it is never imported
at the module level here.

Device and brand names are not referenced: this adapter targets the vendor-
neutral standard profile, so any conforming weight scale is supported. Consumer
body-composition scales that use a proprietary BLE protocol (rather than the
standard Weight Scale Service) are not supported here; their route is the
phase-3 phone-aggregator path (see ``docs/roadmap.md``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, ClassVar

from vitals_on_fhir.adapters.base import ConnectionState, DeviceAdapter
from vitals_on_fhir.adapters.ble import BleConnection, GattCharacteristicParser
from vitals_on_fhir.vitals.base import DeviceInfo, VitalSign
from vitals_on_fhir.vitals.builtin.body_weight import BodyWeight

if TYPE_CHECKING:
    from datetime import datetime, tzinfo

#: GATT UUID of the Weight Scale Service (0x181D), used to filter advertisements.
WEIGHT_SCALE_SERVICE_UUID = "0000181d-0000-1000-8000-00805f9b34fb"

#: GATT UUID of the Weight Measurement characteristic (0x2A9D).
WEIGHT_MEASUREMENT_UUID = "00002a9d-0000-1000-8000-00805f9b34fb"


class WeightScaleBleAdapter(DeviceAdapter):
    """BLE adapter for the standard Bluetooth Weight Scale Service.

    Composes a :class:`~vitals_on_fhir.adapters.BleConnection` configured for the
    Weight Scale Service and delegates the connection lifecycle to it. Yields
    ``BodyWeight`` readings decoded by ``WeightMeasurementParser`` from the Weight
    Measurement characteristic.
    """

    supported_vitals: ClassVar[tuple[type[VitalSign], ...]] = (BodyWeight,)

    def __init__(
        self,
        *,
        device_name: str | None = None,
        on_state_change: Callable[[ConnectionState], Awaitable[None]] | None = None,
        now: Callable[[], datetime] | None = None,
        tz: tzinfo | None = None,
    ) -> None:
        """Initialize the adapter, composing a Weight Scale Service lifecycle.

        Args:
            device_name: Optional BLE advertised-name filter (``VOF_DEVICE_NAME``).
                When set, only advertisements whose name matches are considered,
                in addition to the ``matches`` check.
            on_state_change: Optional async callback invoked on every connection
                state transition, wired by ``cli.py`` to relay state to the
                dashboard.
            now: Optional clock returning a timezone-aware timestamp, forwarded
                to the parser for readings that carry no embedded timestamp.
            tz: Optional timezone in which to interpret a device-supplied zoneless
                timestamp, forwarded to the parser. ``None`` preserves host-local
                behavior.
        """
        self._now = now
        self._tz = tz
        self._connection = BleConnection(
            service_uuid=WEIGHT_SCALE_SERVICE_UUID,
            characteristic_uuid=WEIGHT_MEASUREMENT_UUID,
            matches=self.matches,
            parser_factory=self._build_parser,
            device_name=device_name,
            on_state_change=on_state_change,
        )

    def matches(self, advertisement: object) -> bool:
        """Return ``True`` for any standard weight-scale advertisement.

        Advertisements reaching this predicate are already pre-filtered by the
        Weight Scale Service UUID during the scan, which is authoritative for
        selecting a conforming device — so every candidate matches. The optional
        ``device_name`` filter (applied by the composed ``BleConnection``) remains
        available to disambiguate when several scales are in range.
        """
        return True

    @property
    def device_info(self) -> DeviceInfo:
        """Return vendor-neutral device metadata for a standard weight scale."""
        return DeviceInfo(
            manufacturer="Generic",
            model="Weight Scale",
            identifiers={"profile": "org.bluetooth.service.weight_scale"},
        )

    @property
    def state(self) -> ConnectionState:
        """Current connection state (managed by the composed lifecycle)."""
        return self._connection.state

    async def connect(self) -> None:
        """Scan for, connect to, and subscribe to a weight-scale device."""
        await self._connection.connect()

    async def disconnect(self) -> None:
        """Stop notifications, disconnect, and unblock ``vitals()``."""
        await self._connection.disconnect()

    def vitals(self) -> AsyncIterator[VitalSign]:
        """Yield ``BodyWeight`` readings parsed from BLE indications."""
        return self._connection.vitals()

    def _build_parser(self) -> GattCharacteristicParser:
        """Construct the Weight Measurement parser for the composed lifecycle.

        Imported lazily to respect the package dependency direction
        (``adapters.weight_parser`` imports ``adapters.ble``, so importing it at
        module load here would risk an import cycle).
        """
        from vitals_on_fhir.adapters.weight_parser import WeightMeasurementParser

        return WeightMeasurementParser(
            device_id=self.device_info.identifiers["profile"],
            now=self._now,
            tz=self._tz,
        )
