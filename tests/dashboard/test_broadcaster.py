# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for ``DashboardBroadcaster`` fan-out (Property 16, examples).

The broadcaster serialises each FHIR Observation once and pushes it to every
registered WebSocket client wrapped in an ``observation`` envelope, and pushes a
``connection_state`` envelope to every client on ``on_state_change``. These
tests use an in-memory fake WebSocket (no FastAPI/Starlette, no bleak, no live
server) and drive the async API via ``asyncio.run`` (pytest-asyncio is not
installed). A static-asset check confirms the dashboard carries the mandated
BLE unauthenticated-channel and not-HIPAA/local-only disclaimers.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from fhir.resources.R4B.observation import Observation
from hypothesis import given, settings
from hypothesis import strategies as st

from vitals_on_fhir.dashboard import DashboardBroadcaster
from vitals_on_fhir.fhir import ScalarVitalMapper
from vitals_on_fhir.vitals import HeartRate


class FakeWebSocket:
    """In-memory WebSocket-like double recording every text frame sent.

    Structurally satisfies ``WebSocketLike`` (async ``send_text`` and
    ``close``) so it can be registered with the broadcaster without any web
    framework. Sent frames are recorded in :attr:`messages` for assertions.
    """

    def __init__(self) -> None:
        """Create a fake socket with an empty message log."""
        self.messages: list[str] = []
        self.closed = False

    async def send_text(self, data: str) -> None:
        """Record a text frame instead of sending it over a real socket."""
        self.messages.append(data)

    async def close(self) -> None:
        """Mark the fake socket as closed."""
        self.closed = True


def _make_observation(value: float, device_id: str = "dev-1") -> Observation:
    """Build a FHIR Observation from a ``HeartRate`` via ``ScalarVitalMapper``."""
    reading = HeartRate(
        effective=datetime(2026, 1, 1, tzinfo=UTC),
        device_id=device_id,
        value=value,
    )
    return ScalarVitalMapper().to_observation(
        reading,
        patient_ref="Patient/local-patient",
        device_ref=f"Device/{device_id}",
        issued=datetime(2026, 1, 1, tzinfo=UTC),
    )


# Feature: hr-pipeline, Property 16: Broadcaster fans out FHIR JSON to every client
@settings(max_examples=100)
@given(
    client_count=st.integers(min_value=0, max_value=8),
    value=st.floats(
        min_value=20.0, max_value=250.0, allow_nan=False, allow_infinity=False
    ),
)
def test_broadcaster_fans_out_fhir_json_to_every_client(
    client_count: int, value: float
) -> None:
    """Property 16: every registered client receives one round-tripping observation envelope.

    After ``publish``, each of the ``client_count`` registered fake clients has
    received exactly one message, that message is an ``observation`` envelope,
    and its ``resource`` payload parses back (via ``Observation.model_validate_json``)
    to an Observation equal to the published one (same ``id`` and ``valueQuantity``).

    Validates: Requirements FR-10, FR-6
    """

    async def scenario() -> None:
        broadcaster = DashboardBroadcaster()
        clients = [FakeWebSocket() for _ in range(client_count)]
        for client in clients:
            await broadcaster.register(client)

        observation = _make_observation(value)
        await broadcaster.publish(observation)

        for client in clients:
            # Exactly one frame delivered per client.
            assert len(client.messages) == 1

            envelope = json.loads(client.messages[0])
            assert envelope["type"] == "observation"

            # The resource round-trips to an equal Observation.
            resource_json = json.dumps(envelope["resource"])
            parsed = Observation.model_validate_json(resource_json)
            assert parsed.id == observation.id
            assert float(parsed.valueQuantity.value) == float(
                observation.valueQuantity.value
            )
            assert parsed.code.coding[0].code == observation.code.coding[0].code

    asyncio.run(scenario())


def test_on_state_change_sends_connection_state_envelope_to_all_clients() -> None:
    """Example: ``on_state_change`` pushes a ``connection_state`` envelope to every client.

    Validates: Requirements FR-6, FR-10
    """

    async def scenario() -> None:
        broadcaster = DashboardBroadcaster()
        clients = [FakeWebSocket() for _ in range(3)]
        for client in clients:
            await broadcaster.register(client)

        await broadcaster.on_state_change("DISCONNECTED")

        for client in clients:
            assert len(client.messages) == 1
            envelope = json.loads(client.messages[0])
            assert envelope["type"] == "connection_state"
            assert envelope["state"] == "DISCONNECTED"

    asyncio.run(scenario())


def test_on_state_change_accepts_enum_state_structurally() -> None:
    """Example: an enum-like state contributes its ``value`` to the envelope.

    The broadcaster accepts the state structurally (no adapter import), so an
    ``enum.Enum`` member with a string value serialises to that value.
    """
    import enum

    class _State(enum.Enum):
        CONNECTED = "CONNECTED"

    async def scenario() -> None:
        broadcaster = DashboardBroadcaster()
        client = FakeWebSocket()
        await broadcaster.register(client)

        await broadcaster.on_state_change(_State.CONNECTED)

        envelope = json.loads(client.messages[0])
        assert envelope["type"] == "connection_state"
        assert envelope["state"] == "CONNECTED"

    asyncio.run(scenario())


def test_static_dashboard_contains_ble_and_scope_disclaimers() -> None:
    """Example: the static dashboard carries the mandated security disclaimers.

    ``index.html`` must warn that the standard Bluetooth Heart Rate Service is
    an unauthenticated channel and state the research/educational, not-HIPAA,
    local-only scope (security-privacy.md).

    Validates: Requirements FR-6
    """
    index_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "vitals_on_fhir"
        / "dashboard"
        / "static"
        / "index.html"
    )
    html = index_path.read_text(encoding="utf-8").lower()

    # BLE unauthenticated-channel disclaimer.
    assert "unauthenticated" in html
    assert "heart rate service" in html
    assert "broadcast" in html

    # Not-HIPAA / local-only research-use note.
    assert "hipaa" in html
    assert "not a medical device" in html


def test_late_client_receives_last_connection_state() -> None:
    """A client registering after a state change is told the current state at once.

    The mock adapter "connects" at startup, before any browser has opened the
    WebSocket; without replay the dashboard would never learn it is connected.
    """

    async def scenario() -> tuple[list[str], list[str]]:
        broadcaster = DashboardBroadcaster()
        await broadcaster.on_state_change("connecting")
        await broadcaster.on_state_change("connected")
        late = FakeWebSocket()
        await broadcaster.register(late)
        await broadcaster.on_state_change("disconnected")
        return late.messages, [json.loads(m)["state"] for m in late.messages]

    messages, states = asyncio.run(scenario())

    assert all(json.loads(m)["type"] == "connection_state" for m in messages)
    assert states == ["connected", "disconnected"]


def test_register_before_any_state_sends_nothing() -> None:
    """With no state reported yet, registering does not invent one."""

    async def scenario() -> list[str]:
        broadcaster = DashboardBroadcaster()
        client = FakeWebSocket()
        await broadcaster.register(client)
        return client.messages

    assert asyncio.run(scenario()) == []


def test_dashboard_has_live_chart_assets() -> None:
    """The dashboard page ships the chart container, and the script draws into it."""
    static = Path(__file__).resolve().parents[2] / "src/vitals_on_fhir/dashboard/static"

    assert 'id="hr-chart"' in (static / "index.html").read_text(encoding="utf-8")
    assert "hr-chart" in (static / "app.js").read_text(encoding="utf-8")


def test_reset_tells_every_client_to_start_over() -> None:
    """``reset`` pushes a ``reset`` envelope, in order with the observations around it."""

    async def scenario() -> tuple[list[str], list[str]]:
        broadcaster = DashboardBroadcaster()
        first, second = FakeWebSocket(), FakeWebSocket()
        await broadcaster.register(first)
        await broadcaster.register(second)
        await broadcaster.publish(_make_observation(70.0))
        await broadcaster.reset()
        await broadcaster.publish(_make_observation(50.0))
        return first.messages, second.messages

    first, second = asyncio.run(scenario())

    for messages in (first, second):
        assert [json.loads(m)["type"] for m in messages] == ["observation", "reset", "observation"]
