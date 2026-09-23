# SPDX-License-Identifier: AGPL-3.0-or-later
"""Behavior tests for ``PulseOximeterBleAdapter`` over the composed ``BleConnection``.

Drives the adapter's composed BLE lifecycle end to end with an in-memory fake
``bleak`` (no real Bluetooth stack, no ``hardware`` marker). Confirms, through
the adapter's own public surface and its real ``PlxContinuousMeasurementParser``:

- state transitions ``DISCONNECTED -> CONNECTING -> CONNECTED -> DISCONNECTED``;
- a reserved/unusable SpO2 SFLOAT (parser returns ``None``) is dropped, and a
  subsequent well-formed payload is yielded;
- ``disconnect()`` unblocks a waiting ``vitals()`` consumer;
- a connected adapter emitting no reading for an interval stays ``CONNECTED``
  (silence between readings is not a disconnection).

Requirements: FR-SPO2-4, NFR-SPO2-5, NFR-SPO2-6.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from vitals_on_fhir.adapters import ble as ble_module
from vitals_on_fhir.adapters.base import ConnectionState
from vitals_on_fhir.adapters.builtin.pulse_oximeter_ble import PulseOximeterBleAdapter
from vitals_on_fhir.vitals import OxygenSaturation


def _encode_sfloat(mantissa: int, exponent: int = 0) -> bytes:
    """Encode a 16-bit IEEE-11073 SFLOAT (4-bit exponent, 12-bit mantissa), little-endian."""
    raw = ((exponent & 0x0F) << 12) | (mantissa & 0x0FFF)
    return raw.to_bytes(2, byteorder="little", signed=False)


def _valid_plx_payload(spo2: int = 98) -> bytes:
    """Build a minimal well-formed PLX Continuous Measurement payload (no flags)."""
    return bytes([0x00]) + _encode_sfloat(spo2) + _encode_sfloat(60)


def _reserved_plx_payload() -> bytes:
    """Build a PLX payload whose SpO2 SFLOAT is a reserved/unusable value (parser -> None)."""
    return bytes([0x00]) + _encode_sfloat(0x07FF) + _encode_sfloat(60)


class _FakeDevice:
    """Stand-in for a ``bleak`` ``BLEDevice`` returned by the fake scanner."""

    name = "Fake Pulse Oximeter"
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


def test_connect_transitions_to_connected(fake_bleak: type[_FakeBleak]) -> None:
    """``connect()`` moves the adapter DISCONNECTED -> CONNECTING -> CONNECTED."""
    states: list[ConnectionState] = []

    async def _record(state: ConnectionState) -> None:
        states.append(state)

    adapter = PulseOximeterBleAdapter(on_state_change=_record)

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


def test_reserved_payload_is_dropped_not_yielded(fake_bleak: type[_FakeBleak]) -> None:
    """A reserved-SFLOAT payload (parser -> None) is dropped; the next good one is yielded."""
    adapter = PulseOximeterBleAdapter()

    async def scenario() -> OxygenSaturation:
        await adapter.connect()
        client = fake_bleak.clients[-1]
        assert client.notify_callback is not None
        client.notify_callback(object(), bytearray(_reserved_plx_payload()))
        client.notify_callback(object(), bytearray(_valid_plx_payload(97)))
        try:
            async for vital in adapter.vitals():
                assert isinstance(vital, OxygenSaturation)
                return vital
            raise AssertionError("vitals() ended before yielding")
        finally:
            await adapter.disconnect()

    reading = asyncio.run(scenario())
    assert reading.value == 97.0


def test_disconnect_unblocks_waiting_vitals(fake_bleak: type[_FakeBleak]) -> None:
    """A ``vitals()`` consumer waiting on an empty queue ends when ``disconnect()`` fires."""
    adapter = PulseOximeterBleAdapter()

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

    adapter = PulseOximeterBleAdapter(on_state_change=_record)

    async def scenario() -> None:
        await adapter.connect()
        assert adapter.state == ConnectionState.CONNECTED
        await asyncio.sleep(0.05)
        assert adapter.state == ConnectionState.CONNECTED
        await adapter.disconnect()

    asyncio.run(scenario())
    assert ConnectionState.RECONNECTING not in states
