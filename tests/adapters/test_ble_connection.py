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

    async def _record(state: ConnectionState, reason: str | None = None) -> None:
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


# --- Finding the device: name filter, retries, connected fallback (fix/ble-device-discovery)


class _NamedDevice:
    """A fake ``BLEDevice`` with a chosen advertised name."""

    def __init__(self, name: str | None, address: str = "D9:AF:51:34:DC:33") -> None:
        self.name = name
        self.address = address


def _scanner_returning(*batches: list[object]) -> type:
    """Build a fake scanner whose successive ``discover`` calls return *batches*.

    The last batch repeats once the others are used up.
    """
    remaining = list(batches)

    class _Scanner:
        calls = 0

        @staticmethod
        async def discover(*, service_uuids: list[str]) -> list[object]:  # noqa: ARG004
            _Scanner.calls += 1
            return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return _Scanner


@pytest.fixture
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make connection retries immediate."""
    monkeypatch.setattr(ble_module, "_BACKOFF_INITIAL", 0.0)


def _filtered_connection(
    device_name: str | None,
    states: list[ConnectionState],
    reasons: list[str | None] | None = None,
) -> BleConnection:
    """Build a ``BleConnection`` with a name filter and an accept-all ``matches``.

    Every state goes into *states*; with *reasons*, the reason given alongside
    it (``None`` if none) goes there too.
    """

    async def _record(state: ConnectionState, reason: str | None = None) -> None:
        states.append(state)
        if reasons is not None:
            reasons.append(reason)

    return BleConnection(
        service_uuid=_SERVICE_UUID,
        characteristic_uuid=_CHARACTERISTIC_UUID,
        matches=lambda _adv: True,
        parser_factory=lambda: _StubParser(_hr_from_nonempty),
        device_name=device_name,
        on_state_change=_record,
    )


@pytest.mark.parametrize("device_name", ["smart band 10", "XIAOMI SMART BAND 10 9940", "9940"])
def test_name_filter_matches_part_of_the_name_ignoring_case(
    fake_bleak: type[_FakeBleak], monkeypatch: pytest.MonkeyPatch, device_name: str
) -> None:
    """``VOF_DEVICE_NAME`` selects a device whose advertised name contains it, any case."""
    band = _NamedDevice("Xiaomi Smart Band 10 9940")
    monkeypatch.setattr(fake_bleak, "BleakScanner", _scanner_returning([band]))
    conn = _filtered_connection(device_name, [])

    async def scenario() -> None:
        await conn.connect()
        await conn.disconnect()

    asyncio.run(scenario())
    assert fake_bleak.clients[0]._device is band


def test_device_not_found_is_retried_until_it_appears(
    fake_bleak: type[_FakeBleak], monkeypatch: pytest.MonkeyPatch, no_backoff: None
) -> None:
    """A scan that finds nothing is retried; the state stays CONNECTING until it connects.

    Each failed attempt reports CONNECTING again with the reason, for the
    dashboard; connecting and disconnecting carry none.
    """
    scanner = _scanner_returning([], [], [_NamedDevice("HR strap")])
    monkeypatch.setattr(fake_bleak, "BleakScanner", scanner)
    states: list[ConnectionState] = []
    reasons: list[str | None] = []
    conn = _filtered_connection(None, states, reasons)

    async def scenario() -> None:
        await conn.connect()
        await conn.disconnect()

    asyncio.run(scenario())
    assert scanner.calls == 3
    assert states == [
        ConnectionState.CONNECTING,
        ConnectionState.CONNECTING,
        ConnectionState.CONNECTING,
        ConnectionState.CONNECTED,
        ConnectionState.DISCONNECTED,
    ]
    assert reasons[0] is None
    assert reasons[1] == reasons[2]
    assert reasons[1] is not None and "no device with service 0x180D found" in reasons[1]
    assert "switching its broadcast off and on again can help" in reasons[1]
    assert reasons[3:] == [None, None]


def test_not_found_warning_names_the_devices_the_filter_excluded(
    fake_bleak: type[_FakeBleak],
    monkeypatch: pytest.MonkeyPatch,
    no_backoff: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When the name filter rejects every device, the warning says what was seen and why."""
    band = _NamedDevice("Xiaomi Smart Band 10 9940")
    monkeypatch.setattr(fake_bleak, "BleakScanner", _scanner_returning([band]))
    conn = _filtered_connection("miband10", [])

    async def scenario() -> None:
        task = asyncio.create_task(conn.connect())
        while not any("none matched" in r.getMessage() for r in caplog.records):
            await asyncio.sleep(0)
        await conn.disconnect()
        await asyncio.wait_for(task, timeout=1.0)

    with caplog.at_level("WARNING", logger=ble_module.__name__):
        asyncio.run(scenario())
    message = next(r.getMessage() for r in caplog.records if "none matched" in r.getMessage())
    assert "'Xiaomi Smart Band 10 9940'" in message
    assert "VOF_DEVICE_NAME is 'miband10'" in message
    assert "0x180D" in message
    assert fake_bleak.clients == []


def test_nothing_found_warning_suggests_what_to_check(
    fake_bleak: type[_FakeBleak],
    monkeypatch: pytest.MonkeyPatch,
    no_backoff: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """With no device in sight, the warning points at power, range, broadcast and other links."""
    monkeypatch.setattr(fake_bleak, "BleakScanner", _scanner_returning([]))
    conn = _filtered_connection(None, [])

    async def scenario() -> None:
        task = asyncio.create_task(conn.connect())
        while not caplog.records:
            await asyncio.sleep(0)
        await conn.disconnect()
        await asyncio.wait_for(task, timeout=1.0)

    with caplog.at_level("WARNING", logger=ble_module.__name__):
        asyncio.run(scenario())
    message = caplog.records[0].getMessage()
    assert "no device with service 0x180D found" in message
    assert "not connected to a phone or another app" in message


def test_already_connected_device_is_used_when_nothing_advertises(
    fake_bleak: type[_FakeBleak], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A matching device already connected to the computer (so not advertising) is used."""
    band = _NamedDevice("Xiaomi Smart Band 10 9940")
    looked_up: list[str] = []

    async def _connected(service_uuid: str) -> list[object]:
        looked_up.append(service_uuid)
        return [band]

    monkeypatch.setattr(fake_bleak, "BleakScanner", _scanner_returning([]))
    monkeypatch.setattr(ble_module, "_find_connected_devices", _connected)
    conn = _filtered_connection("Smart Band 10", [])

    async def scenario() -> None:
        await conn.connect()
        assert conn.state == ConnectionState.CONNECTED
        await conn.disconnect()

    asyncio.run(scenario())
    assert looked_up == [_SERVICE_UUID]
    assert fake_bleak.clients[0]._device is band


def test_advertising_device_is_preferred_over_the_connected_lookup(
    fake_bleak: type[_FakeBleak], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The connected-device lookup runs only when no advertisement is accepted."""
    looked_up: list[str] = []

    async def _connected(service_uuid: str) -> list[object]:
        looked_up.append(service_uuid)
        return []

    monkeypatch.setattr(ble_module, "_find_connected_devices", _connected)
    conn = _filtered_connection(None, [])

    async def scenario() -> None:
        await conn.connect()
        await conn.disconnect()

    asyncio.run(scenario())
    assert looked_up == []


def test_failed_subscription_closes_the_link_and_retries(
    fake_bleak: type[_FakeBleak], monkeypatch: pytest.MonkeyPatch, no_backoff: None
) -> None:
    """If subscribing fails after connecting, that link is closed and a new attempt is made.

    BlueZ keeps an abandoned link open and a connected device stops advertising,
    so leaving it open would hide the device from every later scan.
    """
    failures = [OSError("start_notify failed")]
    original_start_notify = _FakeClient.start_notify

    async def flaky_start_notify(
        self: _FakeClient, uuid: str, callback: Callable[[object, bytearray], None]
    ) -> None:
        if failures:
            raise failures.pop()
        await original_start_notify(self, uuid, callback)

    monkeypatch.setattr(_FakeClient, "start_notify", flaky_start_notify)
    states: list[ConnectionState] = []
    conn = _filtered_connection(None, states)

    async def scenario() -> None:
        await conn.connect()
        assert conn.state == ConnectionState.CONNECTED
        await conn.disconnect()

    asyncio.run(scenario())
    first, second = fake_bleak.clients
    assert first.connected is False
    assert first.notify_callback is None
    assert ConnectionState.RECONNECTING not in states


def test_link_closed_after_failed_subscription_does_not_start_a_reconnect(
    fake_bleak: type[_FakeBleak],
) -> None:
    """A disconnect callback from a client that never became live is ignored."""
    conn = _filtered_connection(None, [])
    started: list[bool] = []
    conn._reconnect_loop = lambda: started.append(True)  # type: ignore[method-assign]

    async def scenario() -> None:
        await conn.connect()
        conn._on_disconnected(object())  # some other, abandoned client
        await asyncio.sleep(0)
        await conn.disconnect()

    asyncio.run(scenario())
    assert started == []


def test_disconnect_stops_a_connect_that_is_still_searching(
    fake_bleak: type[_FakeBleak], monkeypatch: pytest.MonkeyPatch, no_backoff: None
) -> None:
    """``disconnect()`` ends the search; ``connect()`` returns without connecting."""
    scanner = _scanner_returning([])
    monkeypatch.setattr(fake_bleak, "BleakScanner", scanner)
    conn = _filtered_connection(None, [])

    async def scenario() -> None:
        task = asyncio.create_task(conn.connect())
        while scanner.calls < 2:
            await asyncio.sleep(0)
        await conn.disconnect()
        await asyncio.wait_for(task, timeout=1.0)

    asyncio.run(scenario())
    assert fake_bleak.clients == []
    assert conn.state == ConnectionState.DISCONNECTED


def test_missing_bluetooth_stack_still_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without ``bleak`` there is nothing to retry: ``connect()`` raises and resets the state."""

    def _unavailable() -> object:
        raise RuntimeError("bleak is required for BLE adapters but is not available")

    monkeypatch.setattr(ble_module, "_import_bleak", _unavailable)
    states: list[ConnectionState] = []
    conn = _filtered_connection(None, states)

    with pytest.raises(RuntimeError, match="bleak is required"):
        asyncio.run(conn.connect())
    assert states == [ConnectionState.CONNECTING, ConnectionState.DISCONNECTED]


def test_disconnect_during_an_attempt_closes_the_new_link(fake_bleak: type[_FakeBleak]) -> None:
    """A link that comes up after ``disconnect()`` is closed, and the state stays DISCONNECTED."""
    states: list[ConnectionState] = []
    conn = _filtered_connection(None, states)
    release = asyncio.Event()
    original_connect = _FakeClient.connect

    async def slow_connect(self: _FakeClient) -> None:
        await release.wait()
        await original_connect(self)

    async def scenario() -> None:
        task = asyncio.create_task(conn.connect())
        while not fake_bleak.clients:
            await asyncio.sleep(0)
        await conn.disconnect()
        release.set()
        await asyncio.wait_for(task, timeout=1.0)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(_FakeClient, "connect", slow_connect)
        asyncio.run(scenario())
    assert fake_bleak.clients[0].connected is False
    assert conn.state == ConnectionState.DISCONNECTED
    assert ConnectionState.CONNECTED not in states


def test_an_error_without_a_message_is_named_in_the_warning(
    fake_bleak: type[_FakeBleak],
    monkeypatch: pytest.MonkeyPatch,
    no_backoff: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A bare ``TimeoutError`` from bleak is reported by its type, not as an empty reason."""
    failures = [TimeoutError()]
    original_connect = _FakeClient.connect

    async def flaky_connect(self: _FakeClient) -> None:
        if failures:
            raise failures.pop()
        await original_connect(self)

    monkeypatch.setattr(_FakeClient, "connect", flaky_connect)
    conn = _filtered_connection(None, [])

    async def scenario() -> None:
        await conn.connect()
        await conn.disconnect()

    with caplog.at_level("WARNING", logger=ble_module.__name__):
        asyncio.run(scenario())
    assert "BLE device not connected: TimeoutError." in caplog.records[0].getMessage()
