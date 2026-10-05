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
from vitals_on_fhir.adapters.builtin.mock import (
    HeartRateScenario,
    HeartRateScenarioControl,
    MockAdapter,
)


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


def test_switching_scenario_glides_then_settles_in_the_new_band() -> None:
    """A live switch moves smoothly to the new rhythm instead of jumping in one reading."""

    async def scenario() -> list[float]:
        adapter = MockAdapter(
            scenario=HeartRateScenario.NORMAL_SINUS_RHYTHM, interval=0, rng=random.Random(3)
        )
        await adapter.connect()
        values: list[float] = []
        async for reading in adapter.vitals():
            values.append(reading.value)  # type: ignore[attr-defined]
            if len(values) == 30:
                adapter.scenario = HeartRateScenario.SINUS_TACHYCARDIA
            if len(values) == 30 + _SETTLE + 100:
                await adapter.disconnect()
        return values

    values = asyncio.run(scenario())
    before, after = values[:30], values[30:]

    assert max(after[0], after[1]) - before[-1] < 35  # no instant jump to ~118
    assert all(100 < v <= 150 for v in after[_SETTLE:])


def test_scenarios_are_reproducible_with_a_seeded_rng() -> None:
    """The same seed gives the same series."""
    for scenario in HeartRateScenario:
        assert _run_scenario(scenario, count=50, seed=7) == _run_scenario(
            scenario, count=50, seed=7
        )


def test_control_lists_options_and_switches_scenario() -> None:
    """``HeartRateScenarioControl`` exposes every scenario and applies a selection."""
    adapter = MockAdapter()
    control = HeartRateScenarioControl(adapter)

    assert control.current == "normal_sinus_rhythm"  # adopted because none was set
    assert [o["id"] for o in control.options()] == [s.value for s in HeartRateScenario]
    assert all(o["label"] and o["description"] for o in control.options())

    control.select("atrial_fibrillation")

    assert control.current == "atrial_fibrillation"
    assert adapter.scenario is HeartRateScenario.ATRIAL_FIBRILLATION


def test_control_rejects_an_unknown_scenario() -> None:
    """An unknown id raises ``ValueError`` and leaves the scenario unchanged."""
    control = HeartRateScenarioControl(MockAdapter(scenario=HeartRateScenario.SINUS_BRADYCARDIA))

    with pytest.raises(ValueError, match="Unknown scenario"):
        control.select("ventricular_tachycardia")

    assert control.current == "sinus_bradycardia"
