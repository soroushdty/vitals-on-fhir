# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract-suite and behavior tests for ``WeightScaleBleAdapter``.

Two concerns live here, mirroring the thermometer adapter tests:

- The reusable ``DeviceAdapterContract`` runs against the WSS BLE adapter with
  the module-level ``bleak`` check skipped (it composes a ``BleConnection``, so
  it is a BLE adapter). These are structural checks only — no connection is
  attempted, so no hardware or ``bleak`` is needed.
- Behavior over the composed ``BleConnection`` is driven end to end with an
  in-memory fake ``bleak`` (no real Bluetooth stack, no ``hardware`` marker),
  confirming through the adapter's public surface and its real
  ``WeightMeasurementParser``: state transitions, a ``None`` parse result is
  dropped, ``disconnect()`` unblocks a waiting ``vitals()`` consumer, and a quiet
  interval while connected is not a disconnection.

``bleak`` is never imported in this file (no ``hardware`` marker).

Requirements: FR-WT-4, FR-WT-8, NFR-WT-6.
"""

from __future__ import annotations

import asyncio
import struct
from collections.abc import Callable

import pytest

from tests.adapters.contract import DeviceAdapterContract
from vitals_on_fhir.adapters import ble as ble_module
from vitals_on_fhir.adapters.base import ConnectionState
from vitals_on_fhir.adapters.builtin.weight_scale_ble import (
    WEIGHT_MEASUREMENT_UUID,
    WEIGHT_SCALE_SERVICE_UUID,
    WeightScaleBleAdapter,
)
from vitals_on_fhir.vitals import BodyWeight


def _valid_weight_payload(kilograms: float = 70.0) -> bytes:
    """Build a minimal well-formed Weight Measurement payload (SI, no optionals).

    Encodes ``kilograms`` as an SI uint16 in 0.005-kg units. Flags byte 0x00: SI
    units, no timestamp, no user ID, no BMI/height.
    """
    raw = round(kilograms / 0.005)
    return bytes([0x00]) + struct.pack("<H", raw)


def _short_weight_payload() -> bytes:
    """Build a payload too short for the mandatory uint16 weight (parser -> None)."""
    return bytes([0x00, 0x01])  # flags + only one weight byte


class _FakeDevice:
    """Stand-in for a ``bleak`` ``BLEDevice`` returned by the fake scanner."""

    name = "Fake Scale"
    address = "AA:BB:CC:DD:EE:FF"


class _FakeClient:
    """Minimal async stand-in for ``bleak.BleakClient`` recording the notify callback."""

    def __init__(self, device: object, disconnected_callback: object = None) -> None:
        self._device = device
        self._disconnected_callback = disconnected_callback
        self.notify_callback: Callable[[object, bytearray], None] | None = None
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def start_notify(self, _uuid: str, callback: Callable[[object, bytearray], None]) -> None:
        self.notify_callback = callback

    async def stop_notify(self, _uuid: str) -> None:
        self.notify_callback = None

    async def disconnect(self) -> None:
        self.connected = False


class _FakeScanner:
    """Fake ``bleak.BleakScanner`` whose ``discover`` returns one fake device."""

    @staticmethod
    async def discover(*, service_uuids: list[str]) -> list[_FakeDevice]:  # noqa: ARG004
        return [_FakeDevice()]


class _FakeBleak:
    """Fake ``bleak`` module exposing just ``BleakScanner`` and ``BleakClient``."""

    BleakScanner = _FakeScanner
    clients: list[_FakeClient] = []

    @classmethod
    def BleakClient(  # noqa: N802 - mirrors bleak's class name
        cls, device: object, disconnected_callback: object = None
    ) -> _FakeClient:
        client = _FakeClient(device, disconnected_callback)
        cls.clients.append(client)
        return client


@pytest.fixture
def fake_bleak(monkeypatch: pytest.MonkeyPatch) -> type[_FakeBleak]:
    """Replace ``_import_bleak`` with a fresh in-memory fake bleak module."""
    _FakeBleak.clients = []
    monkeypatch.setattr(ble_module, "_import_bleak", lambda: _FakeBleak)
    return _FakeBleak


class TestWeightScaleBleAdapterContract(DeviceAdapterContract):
    """``WeightScaleBleAdapter`` satisfies the ``DeviceAdapter`` contract (structural)."""

    adapter_cls = WeightScaleBleAdapter
    requires_hardware = True  # composes BleConnection; skip the bleak static check

    def make_adapter(self) -> WeightScaleBleAdapter:
        """Return a fresh, unconnected WSS BLE adapter for the contract checks."""
        return WeightScaleBleAdapter()


def test_supported_vitals_is_body_weight() -> None:
    """The adapter declares it produces ``BodyWeight`` readings."""
    assert WeightScaleBleAdapter.supported_vitals == (BodyWeight,)


def test_uuids_are_standard_weight_scale_service() -> None:
    """The module declares the standard WSS service (0x181D) and measurement (0x2A9D) UUIDs."""
    assert WEIGHT_SCALE_SERVICE_UUID.startswith("0000181d")
    assert WEIGHT_MEASUREMENT_UUID.startswith("00002a9d")


def test_device_info_is_vendor_neutral() -> None:
    """``device_info`` reports a vendor-neutral standard-profile device."""
    info = WeightScaleBleAdapter().device_info
    assert info.model == "Weight Scale"
    assert info.identifiers["profile"] == "org.bluetooth.service.weight_scale"


def test_matches_accepts_any_prefiltered_advertisement() -> None:
    """``matches`` returns True (service-UUID scan filter is authoritative)."""
    adapter = WeightScaleBleAdapter()

    class _Adv:
        name = "Some Scale"

    assert adapter.matches(_Adv()) is True
    assert adapter.matches(object()) is True


def test_connect_transitions_to_connected(fake_bleak: type[_FakeBleak]) -> None:
    """``connect()`` moves the adapter DISCONNECTED -> CONNECTING -> CONNECTED."""
    states: list[ConnectionState] = []

    async def _record(state: ConnectionState) -> None:
        states.append(state)

    adapter = WeightScaleBleAdapter(on_state_change=_record)

    async def scenario() -> None:
        assert adapter.state == ConnectionState.DISCONNECTED
        await adapter.connect()
        assert adapter.state == ConnectionState.CONNECTED
        await adapter.disconnect()

    asyncio.run(scenario())
    assert states == [
        ConnectionState.CONNECTING,
        ConnectionState.CONNECTED,
        ConnectionState.DISCONNECTED,
    ]


def test_short_payload_is_dropped_not_yielded(fake_bleak: type[_FakeBleak]) -> None:
    """A too-short payload (parser -> None) is dropped; the next good one is yielded."""
    adapter = WeightScaleBleAdapter()

    async def scenario() -> BodyWeight:
        await adapter.connect()
        client = fake_bleak.clients[-1]
        assert client.notify_callback is not None
        client.notify_callback(object(), bytearray(_short_weight_payload()))
        client.notify_callback(object(), bytearray(_valid_weight_payload(72.5)))
        try:
            async for vital in adapter.vitals():
                assert isinstance(vital, BodyWeight)
                return vital
            raise AssertionError("vitals() ended before yielding")
        finally:
            await adapter.disconnect()

    reading = asyncio.run(scenario())
    assert reading.value == pytest.approx(72.5)


def test_disconnect_unblocks_waiting_vitals(fake_bleak: type[_FakeBleak]) -> None:
    """A ``vitals()`` consumer waiting on an empty queue ends when ``disconnect()`` fires."""
    adapter = WeightScaleBleAdapter()

    async def scenario() -> int:
        await adapter.connect()
        yielded = 0

        async def consume() -> None:
            nonlocal yielded
            async for _vital in adapter.vitals():
                yielded += 1

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.02)
        assert not task.done()
        await adapter.disconnect()
        await asyncio.wait_for(task, timeout=1.0)
        return yielded

    yielded = asyncio.run(scenario())
    assert yielded == 0
    assert adapter.state == ConnectionState.DISCONNECTED


def test_silence_between_readings_is_not_a_disconnection(
    fake_bleak: type[_FakeBleak],
) -> None:
    """While connected, an interval with no reading keeps the state CONNECTED."""
    states: list[ConnectionState] = []

    async def _record(state: ConnectionState) -> None:
        states.append(state)

    adapter = WeightScaleBleAdapter(on_state_change=_record)

    async def scenario() -> None:
        await adapter.connect()
        assert adapter.state == ConnectionState.CONNECTED
        await asyncio.sleep(0.05)
        assert adapter.state == ConnectionState.CONNECTED
        await adapter.disconnect()

    asyncio.run(scenario())
    assert ConnectionState.RECONNECTING not in states
