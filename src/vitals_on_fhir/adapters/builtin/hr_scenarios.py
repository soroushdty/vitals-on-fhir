# SPDX-License-Identifier: AGPL-3.0-or-later
"""Simulated heart-rate scenarios for the mock adapter.

These imitate how the heart *rate* behaves in each rhythm or situation.  The
mock emits one beats-per-minute value per reading, so none of this is an ECG,
and none of it is a diagnosis: it is demonstration data.

A scenario is a short list of *phases*.  Each phase has a rate profile (where
the rate settles, how much it wobbles, whether it is regular or chaotic) and,
for scenarios that change over time, how many readings it lasts:

- steady rhythms are a single endless phase;
- episodic scenarios (paroxysmal AF, SVT, flutter, off-wrist, disconnect) hop
  between phases at random, starting with the normal one, and the change is
  abrupt, like the real event;
- exercise runs its phases in order and repeats, with the rate following a
  smooth ramp.

:class:`ScenarioEngine` turns a scenario into one :class:`Tick` per reading.
Allowed imports: stdlib only.
"""

from __future__ import annotations

import enum
import random
from dataclasses import dataclass

_PULL = 0.2  # per-reading pull toward the target rate; sets how fast a switch glides


class HeartRateScenario(enum.Enum):
    """A simulated heart-rate pattern that ``MockAdapter`` can be switched to."""

    NORMAL_SINUS_RHYTHM = "normal_sinus_rhythm"
    SINUS_BRADYCARDIA = "sinus_bradycardia"
    SINUS_TACHYCARDIA = "sinus_tachycardia"
    ATRIAL_FIBRILLATION = "atrial_fibrillation"
    PAROXYSMAL_AF = "paroxysmal_af"
    SVT = "svt"
    ATRIAL_FLUTTER = "atrial_flutter"
    EXERCISE_RAMP = "exercise_ramp"
    OFF_WRIST = "off_wrist"
    DISCONNECT_RECONNECT = "disconnect_reconnect"


@dataclass(frozen=True)
class _Profile:
    """How the rate behaves during one phase.

    Attributes:
        mean: Rate (bpm) the series settles around.
        low: Lowest whole-bpm value once settled.
        high: Highest whole-bpm value once settled.
        step: Standard deviation (bpm) of the per-reading noise.
        irregular: ``True`` for beat-to-beat chaos (each reading drawn
            independently); ``False`` for a smooth, mean-reverting walk.
        mean_to: If set, ``mean`` moves linearly to this over the phase (a ramp).
    """

    mean: float
    low: int
    high: int
    step: float
    irregular: bool = False
    mean_to: float | None = None


@dataclass(frozen=True)
class _Phase:
    """One stretch of a scenario.

    Attributes:
        profile: The rate behaviour while this phase runs.
        length: ``(min, max)`` readings it lasts; ``(0, 0)`` means forever.
        weight: Relative chance of being picked next (episodic scenarios).
        contact: Whether the sensor reports skin contact.
        connected: ``False`` means the device link is down: nothing is emitted.
    """

    profile: _Profile
    length: tuple[int, int] = (0, 0)
    weight: int = 1
    contact: bool = True
    connected: bool = True


@dataclass(frozen=True)
class _Spec:
    """A scenario's text for the dashboard and its phases.

    ``cycle`` runs phases in order, continuing smoothly from one to the next;
    otherwise the next phase is picked at random (never the same one twice in a
    row) and the change is abrupt.
    """

    label: str
    description: str
    group: str
    phases: tuple[_Phase, ...]
    cycle: bool = False


_STEADY = "Steady rhythms"
_EPISODES = "Rhythm episodes"
_OTHER = "Activity and device"

_NSR = _Profile(mean=72.0, low=60, high=100, step=1.2)
_AF = _Profile(mean=125.0, low=70, high=180, step=22.0, irregular=True)

_SPECS: dict[HeartRateScenario, _Spec] = {
    HeartRateScenario.NORMAL_SINUS_RHYTHM: _Spec(
        "Normal sinus rhythm",
        "60-100 bpm, steady and regular",
        _STEADY,
        (_Phase(_NSR),),
    ),
    HeartRateScenario.SINUS_BRADYCARDIA: _Spec(
        "Sinus bradycardia",
        "Below 60 bpm, steady and regular",
        _STEADY,
        (_Phase(_Profile(mean=50.0, low=38, high=59, step=1.0)),),
    ),
    HeartRateScenario.SINUS_TACHYCARDIA: _Spec(
        "Sinus tachycardia",
        "Above 100 bpm, steady and regular",
        _STEADY,
        (_Phase(_Profile(mean=118.0, low=101, high=150, step=1.8)),),
    ),
    HeartRateScenario.ATRIAL_FIBRILLATION: _Spec(
        "Atrial fibrillation",
        "Fast and irregularly irregular, jumping beat to beat",
        _STEADY,
        (_Phase(_AF),),
    ),
    HeartRateScenario.PAROXYSMAL_AF: _Spec(
        "Paroxysmal AF",
        "Normal rhythm that suddenly flips into AF, then back",
        _EPISODES,
        (_Phase(_NSR, (10, 20)), _Phase(_AF, (15, 30))),
    ),
    HeartRateScenario.SVT: _Spec(
        "Supraventricular tachycardia",
        "Normal rhythm, then a sudden, very regular 160-210 bpm that stops just as suddenly",
        _EPISODES,
        (
            _Phase(_NSR, (10, 20)),
            _Phase(_Profile(mean=180.0, low=160, high=210, step=1.0), (15, 30)),
        ),
    ),
    HeartRateScenario.ATRIAL_FLUTTER: _Spec(
        "Atrial flutter",
        "Steady near 150 bpm, sometimes stepping down to 100 or 75",
        _EPISODES,
        (
            _Phase(_Profile(mean=150.0, low=144, high=156, step=0.8), (20, 40), weight=4),
            _Phase(_Profile(mean=100.0, low=95, high=105, step=0.8), (6, 14)),
            _Phase(_Profile(mean=75.0, low=71, high=79, step=0.8), (6, 14)),
        ),
    ),
    HeartRateScenario.EXERCISE_RAMP: _Spec(
        "Exercise and recovery",
        "Rest, ramp up to about 150, hold, then slow recovery (about 2 minutes, repeating)",
        _OTHER,
        (
            _Phase(_Profile(mean=72.0, low=55, high=100, step=1.2), (12, 12)),
            _Phase(_Profile(mean=72.0, low=55, high=165, step=2.0, mean_to=150.0), (40, 40)),
            _Phase(_Profile(mean=150.0, low=130, high=170, step=2.5), (20, 20)),
            _Phase(_Profile(mean=150.0, low=55, high=165, step=2.0, mean_to=72.0), (45, 45)),
        ),
        cycle=True,
    ),
    HeartRateScenario.OFF_WRIST: _Spec(
        "Off-wrist sensor",
        "Normal rhythm, then the sensor loses skin contact and its readings are rejected",
        _OTHER,
        (_Phase(_NSR, (10, 20)), _Phase(_NSR, (14, 22), contact=False)),
    ),
    HeartRateScenario.DISCONNECT_RECONNECT: _Spec(
        "Disconnect and reconnect",
        "Normal rhythm, then the device drops out for a few seconds and reconnects",
        _OTHER,
        (_Phase(_NSR, (12, 24)), _Phase(_NSR, (8, 12), connected=False)),
    ),
}


@dataclass(frozen=True)
class ScenarioInfo:
    """Dashboard-facing description of a scenario."""

    id: str
    label: str
    description: str
    group: str


def scenario_infos() -> list[ScenarioInfo]:
    """Return every scenario, in the order the dashboard lists them."""
    return [
        ScenarioInfo(s.value, spec.label, spec.description, spec.group)
        for s, spec in _SPECS.items()
    ]


@dataclass(frozen=True)
class Tick:
    """What the simulated device does at one reading.

    Attributes:
        bpm: The heart rate in whole bpm, or ``None`` while the link is down.
        contact: Whether the sensor reports skin contact.
        connected: ``False`` while the device link is down.
    """

    bpm: float | None
    contact: bool = True
    connected: bool = True


def _clamp(value: float, low: float, high: float) -> float:
    """Return *value* limited to ``[low, high]``."""
    return min(max(value, low), high)


class ScenarioEngine:
    """Produces one :class:`Tick` per reading for the selected scenario.

    The rate carries over when the scenario is switched, so a regular rhythm
    glides from the old rate to the new one instead of jumping.
    """

    def __init__(self, rng: random.Random) -> None:
        """Create an engine drawing randomness from *rng* (seed it for repeatable output)."""
        self._rng = rng
        self._scenario = HeartRateScenario.NORMAL_SINUS_RHYTHM
        self._started = False
        self._hr: float | None = None
        self._index = 0  # current phase
        self._length = 0  # readings the current phase lasts (0 = forever)
        self._tick = 0  # readings spent in the current phase

    def select(self, scenario: HeartRateScenario) -> None:
        """Switch to *scenario*, starting at its first phase on the next :meth:`step`."""
        self._scenario = scenario
        self._started = False

    def step(self) -> Tick:
        """Advance one reading and return what the device does."""
        spec = _SPECS[self._scenario]
        if not self._started:
            self._enter(spec, 0, abrupt=False)
            self._started = True
        elif self._length and self._tick >= self._length:
            self._enter(spec, self._pick_next(spec), abrupt=not spec.cycle)
        phase = spec.phases[self._index]
        tick = self._tick
        self._tick += 1
        if not phase.connected:
            return Tick(bpm=None, contact=phase.contact, connected=False)
        return Tick(bpm=self._next_bpm(phase.profile, tick), contact=phase.contact)

    def _enter(self, spec: _Spec, index: int, *, abrupt: bool) -> None:
        """Start phase *index*; an abrupt change forgets the previous rate."""
        low, high = spec.phases[index].length
        self._index = index
        self._length = self._rng.randint(low, high) if high else 0
        self._tick = 0
        if abrupt:
            self._hr = None

    def _pick_next(self, spec: _Spec) -> int:
        """Return the next phase: the following one in a cycle, else a random other one."""
        if spec.cycle:
            return (self._index + 1) % len(spec.phases)
        others = [i for i in range(len(spec.phases)) if i != self._index]
        weights = [spec.phases[i].weight for i in others]
        return self._rng.choices(others, weights=weights)[0]

    def _next_bpm(self, profile: _Profile, tick: int) -> float:
        """Return the next whole-bpm reading for *profile*, *tick* readings into its phase."""
        mean = profile.mean
        if profile.mean_to is not None and self._length:
            mean += (profile.mean_to - mean) * min(tick / self._length, 1.0)

        if profile.irregular:
            self._hr = _clamp(self._rng.gauss(mean, profile.step), profile.low, profile.high)
        else:
            current = mean if self._hr is None else self._hr
            value = current + _PULL * (mean - current) + self._rng.gauss(0.0, profile.step)
            if profile.low <= current <= profile.high:
                value = _clamp(value, profile.low, profile.high)  # once inside, stay inside
            self._hr = value
        return float(round(self._hr))
