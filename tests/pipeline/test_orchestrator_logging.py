# SPDX-License-Identifier: AGPL-3.0-or-later
"""Logging-privacy tests for the pipeline orchestrator.

These tests protect FR-3b.6 / NFR-5: a reading's measurement value must never
appear in any log record emitted at ``INFO`` level or above, whether the
reading is accepted, rejected, or fails FHIR construction.

The fast suite drives the orchestrator through :func:`asyncio.run` with bounded
adapters (``pytest-asyncio`` is not installed). ``bleak`` is never imported.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from vitals_on_fhir.adapters.base import ConnectionState, DeviceAdapter
from vitals_on_fhir.adapters.builtin.mock import EmissionMode, MockAdapter
from vitals_on_fhir.fhir import ScalarVitalMapper
from vitals_on_fhir.pipeline.base import ObservationSink
from vitals_on_fhir.pipeline.orchestrator import Orchestrator
from vitals_on_fhir.validation.base import ValidatorChain
from vitals_on_fhir.validation.builtin.validators import (
    DuplicateValidator,
    PlausibleRangeValidator,
    SensorContactValidator,
)
from vitals_on_fhir.vitals.base import DeviceInfo, VitalSign
from vitals_on_fhir.vitals.builtin.heart_rate import HeartRate

if TYPE_CHECKING:
    from fhir.resources.R4B.observation import Observation

_PATIENT_REF = "Patient/local-patient"
_DEVICE_REF = "Device/mock-hr"
_DEVICE_ID = "value-emitter"


class _RecordingSink(ObservationSink):
    """Test sink that records every published Observation."""

    def __init__(self) -> None:
        self.published: list[Observation] = []

    async def publish(self, observation: Observation) -> None:
        """Record the published Observation."""
        self.published.append(observation)


class _ValueEmittingAdapter(DeviceAdapter):
    """Emits exactly one ``HeartRate`` with a caller-supplied value, no ``bleak``.

    Used to exercise Property 15 across a wide range of measurement values that
    the fixed-value :class:`MockAdapter` modes cannot cover on their own.
    """

    supported_vitals: ClassVar[tuple[type[VitalSign], ...]] = (HeartRate,)

    def __init__(self, value: float, *, sensor_contact: bool | None = True) -> None:
        self._value = value
        self._sensor_contact = sensor_contact
        self._state = ConnectionState.DISCONNECTED

    @property
    def device_info(self) -> DeviceInfo:
        """Return a synthetic ``DeviceInfo``."""
        return DeviceInfo(
            manufacturer="vitals-on-fhir",
            model="Value Emitter",
            identifiers={"mock": _DEVICE_ID},
        )

    @property
    def state(self) -> ConnectionState:
        """Return the current simulated connection state."""
        return self._state

    async def connect(self) -> None:
        """Simulate a connection."""
        self._state = ConnectionState.CONNECTED

    async def disconnect(self) -> None:
        """Simulate a disconnection."""
        self._state = ConnectionState.DISCONNECTED

    async def vitals(self) -> AsyncIterator[VitalSign]:
        """Yield a single reading carrying the configured value, then stop."""
        yield HeartRate(
            effective=datetime.now(UTC),
            device_id=_DEVICE_ID,
            value=self._value,
            sensor_contact=self._sensor_contact,
        )
        self._state = ConnectionState.DISCONNECTED


def _fresh_chain() -> ValidatorChain:
    """Build a validator chain with default heart-rate bounds."""
    return ValidatorChain(
        [
            PlausibleRangeValidator(),
            SensorContactValidator(),
            DuplicateValidator(),
        ]
    )


def _run_orchestrator(adapter: DeviceAdapter) -> _RecordingSink:
    """Run the orchestrator to completion against *adapter* and return the sink."""
    sink = _RecordingSink()
    orchestrator = Orchestrator(
        adapter,
        _fresh_chain(),
        ScalarVitalMapper(),
        [sink],
        patient_ref=_PATIENT_REF,
        device_ref=_DEVICE_REF,
    )
    asyncio.run(orchestrator.run())
    return sink


# INFO+ log text that legitimately contains digits: only the configured
# plausible-range bounds. The reading's own value must never appear; these
# strings are excluded so a value that happens to be a substring of the bounds
# text is not counted as a leak (the bounds are config, not measurements).
_CONFIG_DIGIT_TEXT = "20.0 250.0 20 250"


def _value_renderings(value: float) -> set[str]:
    """Return string renderings of *value* that might leak into a log message."""
    candidates = {str(value), repr(value)}
    if value == int(value):
        candidates.add(str(int(value)))
    return candidates


def _is_distinctive(value: float) -> bool:
    """True when *value*'s renderings are long and not substrings of config text.

    Short numeric strings (e.g. ``"0"``) or renderings embedded in the fixed
    bounds text would trigger false positives on substring matching, so the
    property test restricts generated values to distinctive ones.
    """
    return all(
        len(rendering) >= 3 and rendering not in _CONFIG_DIGIT_TEXT
        for rendering in _value_renderings(value)
    )


def _assert_value_absent_from_info_logs(
    records: list[logging.LogRecord], value: float
) -> None:
    """Assert no INFO+ record's message contains any rendering of *value*."""
    needles = _value_renderings(value)
    for record in records:
        if record.levelno < logging.INFO:
            continue
        message = record.getMessage()
        for needle in needles:
            assert needle not in message, (
                f"measurement value {needle!r} leaked into an "
                f"{record.levelname} log: {message!r}"
            )


# Feature: hr-pipeline, Property 15: Measurement values never appear in logs at INFO+
@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    value=st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False),
    sensor_contact=st.sampled_from([True, False, None]),
)
def test_measurement_value_never_in_info_logs(
    caplog: pytest.LogCaptureFixture,
    value: float,
    sensor_contact: bool | None,
) -> None:
    """No INFO+ log record contains a reading's measurement value.

    The generated value spans in-range, implausible, and boundary values, and
    the sensor-contact flag drives both the accepted and rejected paths, so the
    property is checked on processed and rejected readings alike. Values are
    restricted to distinctive renderings so substring matching cannot collide
    with the configured plausible-range bounds that legitimately appear in
    rejection messages.

    **Validates: Requirements FR-3b.6, NFR-5**
    """
    assume(_is_distinctive(value))
    caplog.clear()
    adapter = _ValueEmittingAdapter(value, sensor_contact=sensor_contact)
    with caplog.at_level(logging.INFO):
        _run_orchestrator(adapter)
    _assert_value_absent_from_info_logs(caplog.records, value)


def test_rejected_reading_yields_no_publish(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A rejected reading produces zero sink publishes and leaks no value.

    Example accompanying Property 15: an implausible reading from
    ``MockAdapter`` is rejected by the chain, so the sink never receives an
    Observation, and the implausible value never appears in an INFO+ log.
    """
    caplog.clear()
    adapter = MockAdapter(EmissionMode.IMPLAUSIBLE, count=3)
    with caplog.at_level(logging.INFO):
        sink = _run_orchestrator(adapter)

    assert sink.published == []
    # 300.0 is the fixed implausible value MockAdapter emits.
    _assert_value_absent_from_info_logs(caplog.records, 300.0)


def test_no_sensor_contact_reading_yields_no_publish(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A sensor-contact-lost reading is rejected and never published or logged.

    Example accompanying Property 15 for the sensor-contact rejection branch.
    """
    caplog.clear()
    adapter = MockAdapter(EmissionMode.NO_SENSOR_CONTACT, count=3)
    with caplog.at_level(logging.INFO):
        sink = _run_orchestrator(adapter)

    assert sink.published == []
    # 72.0 is the fixed valid value MockAdapter emits even in NO_SENSOR_CONTACT.
    _assert_value_absent_from_info_logs(caplog.records, 72.0)


def test_accepted_reading_publishes_without_leaking_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An accepted reading is published and its value never appears at INFO+.

    Example accompanying Property 15 for the accepted path: the reading reaches
    the sink but no INFO+ log carries the measurement value.
    """
    caplog.clear()
    adapter = MockAdapter(EmissionMode.VALID, count=1)
    with caplog.at_level(logging.INFO):
        sink = _run_orchestrator(adapter)

    assert len(sink.published) == 1
    _assert_value_absent_from_info_logs(caplog.records, 72.0)
