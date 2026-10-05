# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract-suite wiring for ``MockAdapter``.

Runs the reusable :class:`~tests.adapters.contract.DeviceAdapterContract` suite
against ``MockAdapter`` so the simulated adapter is verified to satisfy the same
structural contract as any real device adapter (FR-9, FR-13, NFR-6). ``bleak``
is never imported here — this is a non-``hardware`` test.
"""

from __future__ import annotations

import asyncio
import random

import pytest

from tests.adapters.contract import DeviceAdapterContract
from vitals_on_fhir.adapters.base import ConnectionState
from vitals_on_fhir.adapters.builtin.hr_scenarios import HeartRateScenario
from vitals_on_fhir.adapters.builtin.mock import HeartRateScenarioControl, MockAdapter


class TestMockAdapterContract(DeviceAdapterContract):
    """``MockAdapter`` must pass the full ``DeviceAdapter`` contract suite."""

    adapter_cls = MockAdapter

    def make_adapter(self) -> MockAdapter:
        """Return a default ``MockAdapter`` instance for the contract checks."""
        return MockAdapter()


# --- Heart-rate scenarios ----------------------------------------------------

_SETTLE = 40  # readings to skip so a switch from another scenario has finished gliding


async def _collect(adapter: MockAdapter) -> list[float]:
    """Connect *adapter* and return the value of every reading it yields."""
    await adapter.connect()
    return [reading.value async for reading in adapter.vitals()]  # type: ignore[attr-defined]


def _run_scenario(scenario: HeartRateScenario, count: int = 400, seed: int = 1) -> list[float]:
    """Return *count* readings from a fresh adapter on *scenario*."""
    adapter = MockAdapter(count=count, scenario=scenario, interval=0, rng=random.Random(seed))
    return asyncio.run(_collect(adapter))


def test_default_mock_emits_fixed_72() -> None:
    """Without a scenario the mock keeps its legacy constant reading."""
    assert asyncio.run(_collect(MockAdapter(count=20))) == [72.0] * 20


@pytest.mark.parametrize("seed", range(5))
def test_normal_sinus_rhythm_is_regular_and_between_60_and_100(seed: int) -> None:
    """NSR stays in 60-100 bpm and changes only a little between readings."""
    values = _run_scenario(HeartRateScenario.NORMAL_SINUS_RHYTHM, seed=seed)

    assert all(60 <= v <= 100 for v in values)
    assert max(abs(b - a) for a, b in zip(values, values[1:], strict=False)) <= 10


@pytest.mark.parametrize("seed", range(5))
def test_sinus_bradycardia_stays_below_60(seed: int) -> None:
    """Sinus bradycardia is always under 60 bpm and still above the plausible floor."""
    values = _run_scenario(HeartRateScenario.SINUS_BRADYCARDIA, seed=seed)

    assert all(38 <= v < 60 for v in values)


@pytest.mark.parametrize("seed", range(5))
def test_sinus_tachycardia_stays_above_100(seed: int) -> None:
    """Sinus tachycardia is always over 100 bpm."""
    values = _run_scenario(HeartRateScenario.SINUS_TACHYCARDIA, seed=seed)

    assert all(100 < v <= 150 for v in values)


def test_atrial_fibrillation_is_fast_and_irregular() -> None:
    """AF jumps around beat to beat, far more than any regular scenario."""
    af = _run_scenario(HeartRateScenario.ATRIAL_FIBRILLATION)
    nsr = _run_scenario(HeartRateScenario.NORMAL_SINUS_RHYTHM)

    def mean_jump(values: list[float]) -> float:
        return sum(abs(b - a) for a, b in zip(values, values[1:], strict=False)) / (len(values) - 1)

    assert all(70 <= v <= 180 for v in af)
    assert mean_jump(af) > 5 * mean_jump(nsr)
    assert sum(af) / len(af) > 100


def test_starting_a_scenario_begins_at_its_own_rate_with_nothing_carried_over() -> None:
    """A restart does not glide from the old rate: the very first reading is in the new band."""

    async def run() -> tuple[float, float]:
        adapter = MockAdapter(
            scenario=HeartRateScenario.SINUS_TACHYCARDIA, interval=0, rng=random.Random(3)
        )
        await adapter.connect()
        stream = adapter.vitals()
        before = 0.0
        for _ in range(30):
            before = (await anext(stream)).value  # type: ignore[attr-defined]
        adapter.scenario = HeartRateScenario.SINUS_BRADYCARDIA
        after = (await anext(stream)).value  # type: ignore[attr-defined]
        await stream.aclose()  # type: ignore[attr-defined]
        return before, after

    before, after = asyncio.run(run())

    assert before > 100
    assert 38 <= after < 60


def test_scenarios_are_reproducible_with_a_seeded_rng() -> None:
    """The same seed gives the same series."""
    for scenario in HeartRateScenario:
        assert _run_scenario(scenario, count=50, seed=7) == _run_scenario(
            scenario, count=50, seed=7
        )


def test_control_lists_options_and_starts_a_scenario() -> None:
    """``HeartRateScenarioControl`` exposes every scenario and starts the chosen one."""
    adapter = MockAdapter()
    control = HeartRateScenarioControl(adapter)

    assert control.current == "normal_sinus_rhythm"  # adopted because none was set
    assert [o["id"] for o in control.options()] == [s.value for s in HeartRateScenario]
    assert all(o["label"] and o["description"] for o in control.options())

    control.start("atrial_fibrillation")

    assert control.current == "atrial_fibrillation"
    assert adapter.scenario is HeartRateScenario.ATRIAL_FIBRILLATION


def test_control_rejects_an_unknown_scenario() -> None:
    """An unknown id raises ``ValueError`` and leaves the scenario unchanged."""
    control = HeartRateScenarioControl(MockAdapter(scenario=HeartRateScenario.SINUS_BRADYCARDIA))

    with pytest.raises(ValueError, match="Unknown scenario"):
        control.start("ventricular_tachycardia")

    assert control.current == "sinus_bradycardia"


# --- Off-wrist and disconnect through the adapter ----------------------------


def test_off_wrist_scenario_flags_lost_sensor_contact_on_readings() -> None:
    """Off-wrist readings carry ``sensor_contact=False``, so the validator chain rejects them."""
    adapter = MockAdapter(
        count=120, scenario=HeartRateScenario.OFF_WRIST, interval=0, rng=random.Random(1)
    )

    async def readings() -> list[bool | None]:
        await adapter.connect()
        return [r.sensor_contact async for r in adapter.vitals()]  # type: ignore[attr-defined]

    contact = asyncio.run(readings())

    assert contact[:10] == [True] * 10
    assert False in contact and contact.count(True) > 20


def test_disconnect_scenario_reports_a_dropout_and_goes_quiet() -> None:
    """The mock reports RECONNECTING then CONNECTED, and yields nothing in between."""
    events: list[str] = []

    async def record(state: ConnectionState) -> None:
        events.append(state.value)

    adapter = MockAdapter(
        count=60,
        scenario=HeartRateScenario.DISCONNECT_RECONNECT,
        interval=0,
        rng=random.Random(1),
        on_state_change=record,
    )

    async def run() -> None:
        await adapter.connect()
        async for _ in adapter.vitals():
            events.append("reading")

    asyncio.run(run())

    assert events[:3] == ["connecting", "connected", "reading"]
    assert "reconnecting" in events
    drop = events.index("reconnecting")
    back = events.index("connected", drop)
    assert "reading" not in events[drop:back]  # silent while the link is down
    assert events[back + 1] == "reading"  # and resumes on its own
    assert events.count("reading") == 60


def test_switching_away_from_a_dropout_restores_the_connection() -> None:
    """Picking another scenario while the link is down reconnects on the very next tick."""
    states: list[ConnectionState] = []

    async def on_state(state: ConnectionState) -> None:
        states.append(state)
        if state == ConnectionState.RECONNECTING:
            # What the dashboard's PUT does mid-dropout.
            adapter.scenario = HeartRateScenario.NORMAL_SINUS_RHYTHM

    adapter = MockAdapter(
        count=60,
        scenario=HeartRateScenario.DISCONNECT_RECONNECT,
        interval=0,
        rng=random.Random(1),
        on_state_change=on_state,
    )

    async def run() -> None:
        await adapter.connect()
        async for _ in adapter.vitals():
            pass

    asyncio.run(run())

    drop = states.index(ConnectionState.RECONNECTING)
    assert states[drop + 1] == ConnectionState.CONNECTED  # straight back, not after 8-12 ticks
    assert states.count(ConnectionState.RECONNECTING) == 1  # and no further dropouts


# --- Restart: clearing the previous run, and starting at once ---------------


def test_restart_hook_runs_between_the_old_run_and_the_new_one() -> None:
    """``on_restart`` fires once per start, after the last old reading and before the first new."""
    events: list[str] = []

    async def on_restart() -> None:
        events.append("restart")

    adapter = MockAdapter(
        scenario=HeartRateScenario.SINUS_TACHYCARDIA,
        interval=0,
        rng=random.Random(5),
        on_restart=on_restart,
    )

    async def run() -> None:
        await adapter.connect()
        stream = adapter.vitals()
        for _ in range(3):
            reading = await anext(stream)
            events.append("old" if reading.value > 100 else "new")  # type: ignore[attr-defined]
        adapter.scenario = HeartRateScenario.SINUS_BRADYCARDIA
        for _ in range(3):
            reading = await anext(stream)
            events.append("old" if reading.value > 100 else "new")  # type: ignore[attr-defined]
        await stream.aclose()  # type: ignore[attr-defined]

    asyncio.run(run())

    assert events == ["old", "old", "old", "restart", "new", "new", "new"]  # not at first start


def test_restarting_the_running_scenario_also_clears_and_restarts() -> None:
    """Starting the scenario that is already running is a restart, not a no-op."""
    restarts = 0

    async def on_restart() -> None:
        nonlocal restarts
        restarts += 1

    adapter = MockAdapter(
        scenario=HeartRateScenario.NORMAL_SINUS_RHYTHM,
        interval=0,
        rng=random.Random(2),
        on_restart=on_restart,
    )

    async def run() -> None:
        await adapter.connect()
        stream = adapter.vitals()
        await anext(stream)
        adapter.scenario = HeartRateScenario.NORMAL_SINUS_RHYTHM
        await anext(stream)
        await stream.aclose()  # type: ignore[attr-defined]

    asyncio.run(run())

    assert restarts == 1


def test_a_restart_does_not_wait_out_the_reading_interval() -> None:
    """With a 30 s interval, a restart still produces its first reading almost at once."""
    adapter = MockAdapter(
        scenario=HeartRateScenario.NORMAL_SINUS_RHYTHM, interval=30, rng=random.Random(1)
    )

    async def run() -> float:
        await adapter.connect()
        stream = adapter.vitals()
        await anext(stream)  # first reading arrives immediately; the next is 30 s away
        loop = asyncio.get_running_loop()
        asyncio.get_running_loop().call_later(
            0.05, lambda: setattr(adapter, "scenario", HeartRateScenario.SINUS_BRADYCARDIA)
        )
        started = loop.time()
        await asyncio.wait_for(anext(stream), timeout=5)
        elapsed = loop.time() - started
        await adapter.disconnect()
        return elapsed

    assert asyncio.run(run()) < 2
