# SPDX-License-Identifier: AGPL-3.0-or-later
"""Behavior of the simulated heart-rate scenarios (``ScenarioEngine``).

Each test drives the engine directly with a seeded RNG, so runs are fast and
repeatable, and checks the property that makes the scenario recognisable.
"""

from __future__ import annotations

import random

import pytest

from vitals_on_fhir.adapters.builtin.hr_scenarios import (
    HeartRateScenario,
    ScenarioEngine,
    Tick,
    scenario_infos,
)

_SEEDS = range(5)


def _ticks(scenario: HeartRateScenario, count: int, seed: int = 1) -> list[Tick]:
    """Return *count* ticks from a fresh engine on *scenario*."""
    engine = ScenarioEngine(random.Random(seed))
    engine.select(scenario)
    return [engine.step() for _ in range(count)]


def _bpm(scenario: HeartRateScenario, count: int, seed: int = 1) -> list[float]:
    """Return the heart rate of every tick (the link is never down for these)."""
    values = [t.bpm for t in _ticks(scenario, count, seed)]
    assert all(v is not None for v in values)
    return [v for v in values if v is not None]


def _longest_run(flags: list[bool]) -> int:
    """Return the length of the longest run of ``True`` in *flags*."""
    best = run = 0
    for flag in flags:
        run = run + 1 if flag else 0
        best = max(best, run)
    return best


def _diffs(values: list[float]) -> list[float]:
    """Return the absolute change between consecutive readings."""
    return [abs(b - a) for a, b in zip(values, values[1:], strict=False)]


def test_every_scenario_has_a_label_description_and_group() -> None:
    """The dashboard can render every scenario, and ids match the enum."""
    infos = scenario_infos()

    assert [i.id for i in infos] == [s.value for s in HeartRateScenario]
    assert all(i.label and i.description and i.group for i in infos)
    assert len({i.label for i in infos}) == len(infos)


@pytest.mark.parametrize("seed", _SEEDS)
def test_exercise_rests_ramps_peaks_and_recovers(seed: int) -> None:
    """One ~2 minute cycle: rest, climb to about 150, hold, then come back down, repeatedly."""
    bpm = _bpm(HeartRateScenario.EXERCISE_RAMP, 250, seed)

    def mean(values: list[float]) -> float:
        return sum(values) / len(values)

    assert max(bpm[:12]) <= 100  # resting
    assert mean(bpm[20:25]) < mean(bpm[40:45]) < mean(bpm[58:63])  # climbing
    assert mean(bpm[62:72]) > 135  # peak
    assert mean(bpm[112:117]) < 100  # recovered
    assert max(bpm[120:129]) <= 100  # resting again: the cycle repeats
    assert max(_diffs(bpm)) < 20  # smooth, never a jump


@pytest.mark.parametrize("seed", _SEEDS)
def test_paroxysmal_af_starts_normal_then_flips_in_and_out_of_af(seed: int) -> None:
    """Calm stretches and chaotic stretches both occur, starting calm; changes are abrupt."""
    bpm = _bpm(HeartRateScenario.PAROXYSMAL_AF, 300, seed)
    jumps = _diffs(bpm)

    assert max(bpm[:10]) <= 100 and max(_diffs(bpm[:10])) < 6  # starts as normal rhythm
    assert _longest_run([j <= 6 for j in jumps]) >= 10  # a calm normal stretch
    assert max(sum(jumps[i : i + 10]) / 10 for i in range(len(jumps) - 10)) > 12  # an AF stretch
    assert max(jumps) > 40  # abrupt onset or end


@pytest.mark.parametrize("seed", _SEEDS)
def test_svt_jumps_to_a_fast_regular_rate_and_stops_abruptly(seed: int) -> None:
    """SVT is a sudden, very regular 160-210 bpm episode between stretches of normal rhythm."""
    bpm = _bpm(HeartRateScenario.SVT, 300, seed)
    fast = [v >= 160 for v in bpm]
    normal = [v <= 100 for v in bpm]

    assert _longest_run(normal) >= 10
    assert _longest_run(fast) >= 15
    assert all(v <= 100 or v >= 160 for v in bpm)  # nothing in between: no gliding
    assert max(_diffs(bpm)) > 60  # abrupt onset
    start = fast.index(True)
    episode = bpm[start : start + 15]
    assert max(episode) - min(episode) <= 8  # very regular


@pytest.mark.parametrize("seed", _SEEDS)
def test_atrial_flutter_plateaus_near_150_and_steps_to_100_or_75(seed: int) -> None:
    """Flutter sits near 150 (2:1 block) and sometimes steps to 100 (3:1) or 75 (4:1)."""
    bpm = _bpm(HeartRateScenario.ATRIAL_FLUTTER, 400, seed)

    assert all(144 <= v <= 156 for v in bpm[:20])  # starts on the 2:1 plateau
    assert sum(144 <= v <= 156 for v in bpm) > len(bpm) / 2  # mostly 150
    assert any(95 <= v <= 105 for v in bpm) or any(71 <= v <= 79 for v in bpm)
    assert all(71 <= v <= 156 for v in bpm)


@pytest.mark.parametrize("seed", _SEEDS)
def test_off_wrist_loses_sensor_contact_in_stretches(seed: int) -> None:
    """Contact starts good, drops for 14-22 readings, returns, and repeats; the link stays up."""
    ticks = _ticks(HeartRateScenario.OFF_WRIST, 200, seed)
    contact = [t.contact for t in ticks]

    assert all(contact[:10])
    assert not all(contact) and any(contact[10:])
    assert _longest_run([not c for c in contact]) >= 14
    assert all(t.connected and t.bpm is not None for t in ticks)


@pytest.mark.parametrize("seed", _SEEDS)
def test_disconnect_drops_the_link_in_stretches_with_no_readings(seed: int) -> None:
    """The link starts up, drops for 8-12 readings (no values), and comes back."""
    ticks = _ticks(HeartRateScenario.DISCONNECT_RECONNECT, 200, seed)
    linked = [t.connected for t in ticks]

    assert all(linked[:12])
    assert not all(linked) and any(linked[12:])
    assert 8 <= _longest_run([not c for c in linked]) <= 12
    assert all((t.bpm is None) == (not t.connected) for t in ticks)


def test_selecting_a_scenario_restarts_it_from_the_beginning() -> None:
    """A new scenario starts on its normal phase at its own rate, with nothing carried over."""
    engine = ScenarioEngine(random.Random(4))
    engine.select(HeartRateScenario.ATRIAL_FIBRILLATION)
    for _ in range(30):
        engine.step()

    engine.select(HeartRateScenario.SVT)
    first = [t.bpm for t in (engine.step() for _ in range(10))]

    assert all(v is not None and 60 <= v <= 100 for v in first)  # normal from the first reading
    assert max(_diffs([v for v in first if v is not None])) < 6  # no glide down from AF


def test_selecting_the_same_scenario_again_starts_it_over() -> None:
    """Restarting an episodic scenario returns it to its first (normal) phase."""
    engine = ScenarioEngine(random.Random(9))
    engine.select(HeartRateScenario.SVT)
    ticks = [engine.step().bpm for _ in range(60)]
    assert any(v is not None and v >= 160 for v in ticks)  # an SVT episode has happened

    engine.select(HeartRateScenario.SVT)

    assert all(t.bpm is not None and t.bpm <= 100 for t in (engine.step() for _ in range(10)))
