# SPDX-License-Identifier: AGPL-3.0-or-later
"""Behavior tests for the reusable ``BleConnection`` lifecycle.

These exercise the profile-agnostic BLE lifecycle that both the heart-rate and
blood-pressure adapters compose, without any real Bluetooth stack. ``bleak`` is
never imported: ``BleConnection`` obtains it through the module-level
``_import_bleak`` helper, which these tests replace with an in-memory fake
scanner/client via ``monkeypatch``. The file therefore carries no ``hardware``
marker and imports no ``bleak``.

Covered behavior (Task 9 / FR-HH-4, FR-HH-6, NFR-HH-6):

- state transitions ``DISCONNECTED -> CONNECTING -> CONNECTED -> DISCONNECTED``;
- malformed payloads (parser returns ``None``) are dropped, not yielded;
- ``disconnect()`` unblocks a waiting ``vitals()`` consumer;
- a connected adapter emitting no reading for an interval stays ``CONNECTED``
  (silence between readings is not a disconnection).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from vitals_on_fhir.adapters import ble as ble_module
from vitals_on_fhir.adapters.base import ConnectionState
from vitals_on_fhir.adapters.ble import BleConnection, GattCharacteristicParser
from vitals_on_fhir.vitals.base import VitalSign
from vitals_on_fhir.vitals.builtin.heart_rate import HeartRate

_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
_CHARACTERISTIC_UUID = "00002a37-0000-1000-8000-00805f9b34fb"


class _StubParser(GattCharacteristicParser):
    """Parser stub: a non-empty payload becomes a ``HeartRate``; empty -> ``None``.

    Lets a test push a well-formed and a malformed payload through the real
    ``BleConnection`` queue-drain path without needing the byte-level HR parser.
    """

    def __init__(self, make_vital: Callable[[bytes], VitalSign | None]) -> None:
        self._make_vital = make_vital

    def parse(self, data: bytes) -> VitalSign | None:
        """Delegate to the injected function so tests control drop vs yield."""
        return self._make_vital(data)


class _FakeDevice:
    """Stand-in for a ``bleak`` ``BLEDevice`` returned by the fake scanner."""

    name = "Fake HR Device"
    address = "AA:BB:CC:DD:EE:FF"


class _FakeClient:
    """Minimal async stand-in for ``bleak.BleakClient``.

    Records the notification callback registered via ``start_notify`` so the
    test can push payloads through the same threadsafe path a real device would.
    """

    def __init__(self, device: object, disconnected_callback: object = None) -> None:
        self._device = device
        self._disconnected_callback = disconnected_callback
        self.notify_callback: Callable[[object, bytearray], None] | None = None
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def start_notify(
        self, _uuid: str, callback: Callable[[object, bytearray], None]
    ) -> None:
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


def _hr_from_nonempty(data: bytes) -> VitalSign | None:
    """Return a valid ``HeartRate`` for a non-empty payload, else ``None``."""
    if not data:
        return None
    from datetime import UTC, datetime

    return HeartRate(
        effective=datetime.now(UTC),
        device_id="fake",
        value=72.0,
        sensor_contact=True,
    )


def _make_connection(
    parser: GattCharacteristicParser,
    states: list[ConnectionState],
) -> BleConnection:
    """Build a ``BleConnection`` that records every state transition into ``states``."""

    async def _record(state: ConnectionState) -> None:
        states.append(state)

    return BleConnection(
        service_uuid=_SERVICE_UUID,
        characteristic_uuid=_CHARACTERISTIC_UUID,
        matches=lambda _adv: True,
        parser_factory=lambda: parser,
        on_state_change=_record,
    )


def test_connect_transitions_to_connected(fake_bleak: type[_FakeBleak]) -> None:
    """``connect()`` moves DISCONNECTED -> CONNECTING -> CONNECTED."""
    states: list[ConnectionState] = []
    conn = _make_connection(_StubParser(_hr_from_nonempty), states)

    async def scenario() -> None:
        assert conn.state == ConnectionState.DISCONNECTED
        await conn.connect()
        assert conn.state == ConnectionState.CONNECTED
        await conn.disconnect()

    asyncio.run(scenario())
    assert states == [
        ConnectionState.CONNECTING,
        ConnectionState.CONNECTED,
        ConnectionState.DISCONNECTED,
    ]


def test_malformed_payload_is_dropped_not_yielded(fake_bleak: type[_FakeBleak]) -> None:
    """An empty payload (parser -> ``None``) is dropped; the next good one is yielded."""
    states: list[ConnectionState] = []
    conn = _make_connection(_StubParser(_hr_from_nonempty), states)

    async def scenario() -> HeartRate:
        await conn.connect()
        client = fake_bleak.clients[-1]
        assert client.notify_callback is not None
        # First a malformed (empty) payload, then a well-formed one.
        client.notify_callback(object(), bytearray(b""))
        client.notify_callback(object(), bytearray(b"\x00\x48"))
        try:
            async for vital in conn.vitals():
                assert isinstance(vital, HeartRate)
                return vital
            raise AssertionError("vitals() ended before yielding")
        finally:
            await conn.disconnect()

    reading = asyncio.run(scenario())
    assert reading.value == 72.0


def test_disconnect_unblocks_waiting_vitals(fake_bleak: type[_FakeBleak]) -> None:
    """A ``vitals()`` consumer waiting on an empty queue ends when ``disconnect()`` fires."""
    states: list[ConnectionState] = []
    conn = _make_connection(_StubParser(_hr_from_nonempty), states)

    async def scenario() -> int:
        await conn.connect()
        yielded = 0

        async def consume() -> None:
            nonlocal yielded
            async for _vital in conn.vitals():
                yielded += 1

        task = asyncio.create_task(consume())
        # No payloads pushed: the consumer is blocked on the queue.
        await asyncio.sleep(0.02)
        assert not task.done()
        await conn.disconnect()
        await asyncio.wait_for(task, timeout=1.0)
        return yielded

    yielded = asyncio.run(scenario())
    assert yielded == 0
    assert conn.state == ConnectionState.DISCONNECTED


def test_silence_between_readings_is_not_a_disconnection(
    fake_bleak: type[_FakeBleak],
) -> None:
    """While connected, an interval with no reading keeps the state CONNECTED (FR-HH-6)."""
    states: list[ConnectionState] = []
    conn = _make_connection(_StubParser(_hr_from_nonempty), states)

    async def scenario() -> None:
        await conn.connect()
        assert conn.state == ConnectionState.CONNECTED
        # Simulate an intermittent device: no notifications for an interval.
        await asyncio.sleep(0.05)
        assert conn.state == ConnectionState.CONNECTED
        await conn.disconnect()

    asyncio.run(scenario())
    # No RECONNECTING transition was triggered by the quiet interval.
    assert ConnectionState.RECONNECTING not in states
