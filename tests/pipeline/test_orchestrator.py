# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the pipeline orchestrator (``pipeline/orchestrator.py``).

Uses ``MockAdapter`` as the vital-sign source, the real ``ScalarVitalMapper``
(resolved via the injected mapper registry), and a ``ValidatorChain`` assembled
from the shipped validators. Sinks are lightweight fakes implementing
``ObservationSink``.
No ``bleak`` import; async tests run via the ``asyncio.run`` pattern because
``pytest-asyncio`` is not installed.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

from hypothesis import given, settings
from hypothesis import strategies as st

from vitals_on_fhir.adapters.builtin.mock import EmissionMode, MockAdapter
from vitals_on_fhir.fhir import ScalarVitalMapper, VitalMapper, default_mapper_registry
from vitals_on_fhir.pipeline.base import ObservationSink
from vitals_on_fhir.pipeline.orchestrator import Orchestrator
from vitals_on_fhir.validation import (
    DuplicateValidator,
    PlausibleRangeValidator,
    SensorContactValidator,
    ValidatorChain,
)
from vitals_on_fhir.vitals import HeartRate
from vitals_on_fhir.vitals.base import DeviceInfo, VitalSign

if TYPE_CHECKING:
    from fhir.resources.R4B.observation import Observation

_PATIENT_REF = "Patient/local-patient"
_DEVICE_REF = "Device/mock-hr"


class RecordingSink(ObservationSink):
    """Sink that records every Observation it receives via ``publish``."""

    def __init__(self) -> None:
        self.received: list[Observation] = []

    async def publish(self, observation: Observation) -> None:
        """Record the published Observation."""
        self.received.append(observation)


class FailingSink(ObservationSink):
    """Sink that always raises on ``publish`` and counts each attempt."""

    def __init__(self) -> None:
        self.attempts = 0

    async def publish(self, observation: Observation) -> None:
        """Raise unconditionally to simulate a broken sink."""
        self.attempts += 1
        msg = "simulated sink failure"
        raise RuntimeError(msg)


def _make_chain() -> ValidatorChain:
    """Build a validator chain in the canonical registration order."""
    return ValidatorChain(
        [
            PlausibleRangeValidator(),
            SensorContactValidator(),
            DuplicateValidator(),
        ]
    )


# Feature: hr-pipeline, Property 17: One failing sink does not stop the others
@settings(max_examples=150)
@given(failing_mask=st.lists(st.booleans(), min_size=1, max_size=6))
def test_property_17_failing_sink_does_not_stop_others(
    failing_mask: list[bool],
) -> None:
    """A failing sink never prevents the non-failing sinks from receiving readings.

    For an arbitrary subset of sinks that raise on ``publish``, every
    non-failing sink still receives every Observation produced by the pipeline.

    Validates: Requirements FR-ORCH
    """
    count = 3
    sinks: list[ObservationSink] = [
        FailingSink() if fails else RecordingSink() for fails in failing_mask
    ]
    recording = [s for s in sinks if isinstance(s, RecordingSink)]

    # DuplicateValidator rejects identical (device_id, effective, value) triples;
    # MockAdapter varies `effective` per reading so every VALID reading passes.
    orchestrator = Orchestrator(
        MockAdapter(EmissionMode.VALID, interval=0.0, count=count),
        _make_chain(),
        default_mapper_registry(),
        sinks,
        patient_ref=_PATIENT_REF,
        device_ref=_DEVICE_REF,
    )

    asyncio.run(orchestrator.run())

    for sink in recording:
        assert len(sink.received) == count, (
            "non-failing sink should receive every accepted Observation "
            "regardless of other sinks failing"
        )


def test_observations_from_a_simulated_device_are_labelled_htest() -> None:
    """The orchestrator labels every Observation from the mock as test data (ADR-0002)."""
    sink = RecordingSink()
    orchestrator = Orchestrator(
        MockAdapter(EmissionMode.VALID, interval=0.0, count=2),
        _make_chain(),
        default_mapper_registry(),
        [sink],
        patient_ref=_PATIENT_REF,
        device_ref=_DEVICE_REF,
    )

    asyncio.run(orchestrator.run())

    assert len(sink.received) == 2
    for observation in sink.received:
        labels = [(label.system, label.code) for label in observation.meta.security or []]
        assert labels == [("http://terminology.hl7.org/CodeSystem/v3-ActReason", "HTEST")]


def test_observations_from_a_real_device_carry_no_test_label() -> None:
    """Without ``DeviceInfo.simulated`` nothing is labelled as test data."""

    class _RealLookingMock(MockAdapter):
        @property
        def device_info(self) -> DeviceInfo:
            # Same identifiers (MockAdapter reads "mock"), but not simulated.
            return DeviceInfo(manufacturer="Acme", model="Band", identifiers={"mock": "1"})

    sink = RecordingSink()
    orchestrator = Orchestrator(
        _RealLookingMock(EmissionMode.VALID, interval=0.0, count=2),
        _make_chain(),
        default_mapper_registry(),
        [sink],
        patient_ref=_PATIENT_REF,
        device_ref=_DEVICE_REF,
    )

    asyncio.run(orchestrator.run())

    assert len(sink.received) == 2
    assert all(not observation.meta.security for observation in sink.received)


class _CountingMapper(VitalMapper):
    """Delegates to ``ScalarVitalMapper`` and counts the readings it maps."""

    def __init__(self) -> None:
        self.calls = 0
        self._inner = ScalarVitalMapper()

    def to_observation(
        self, vital: VitalSign, patient_ref: str, device_ref: str, issued: datetime
    ) -> Observation:
        self.calls += 1
        return self._inner.to_observation(vital, patient_ref, device_ref, issued)


def test_readings_are_mapped_by_the_injected_registry() -> None:
    """A mapper registered in the injected registry maps the readings (#38)."""
    mapper = _CountingMapper()
    mappers = default_mapper_registry()
    mappers.register(HeartRate, mapper)
    sink = RecordingSink()
    orchestrator = Orchestrator(
        MockAdapter(EmissionMode.VALID, interval=0.0, count=3),
        _make_chain(),
        mappers,
        [sink],
        patient_ref=_PATIENT_REF,
        device_ref=_DEVICE_REF,
    )

    asyncio.run(orchestrator.run())

    assert mapper.calls == 3
    assert len(sink.received) == 3


def test_registering_a_mapper_does_not_leak_into_other_registries() -> None:
    """Each default registry is independent; there is no shared module state."""
    first = default_mapper_registry()
    first.register(HeartRate, _CountingMapper())

    assert isinstance(default_mapper_registry().resolve(HeartRate), ScalarVitalMapper)
