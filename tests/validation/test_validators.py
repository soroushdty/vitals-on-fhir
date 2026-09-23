# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the validator chain and built-in validators."""

from __future__ import annotations

from datetime import UTC, datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from vitals_on_fhir.validation.base import ValidationResult, Validator, ValidatorChain
from vitals_on_fhir.validation.builtin.validators import (
    PlausibleRangeValidator,
    SensorContactValidator,
)
from vitals_on_fhir.vitals.base import VitalSign
from vitals_on_fhir.vitals.builtin.heart_rate import HeartRate


class _StubValidator(Validator):
    """Deterministic validator used to compose ordered chains in tests.

    Accepts or rejects unconditionally based on ``accept``, independent of the
    reading, so chain ordering can be verified precisely.
    """

    name = "stub"

    def __init__(self, *, accept: bool, name: str) -> None:
        self._accept = accept
        self.name = name

    def check(self, vital: VitalSign) -> ValidationResult:
        """Return a fixed result regardless of *vital*."""
        return ValidationResult(
            accepted=self._accept,
            validator_name=self.name,
            reason=None if self._accept else f"rejected-by-{self.name}",
        )


def _make_reading() -> HeartRate:
    """Build a minimal timezone-aware ``HeartRate`` reading for chain tests."""
    return HeartRate(effective=datetime.now(tz=UTC), device_id="dev-1", value=72.0)


# Feature: hr-pipeline, Property 6: Validator chain returns the first rejection
@given(decisions=st.lists(st.booleans(), min_size=0, max_size=8))
def test_validator_chain_returns_first_rejection(decisions: list[bool]) -> None:
    """Property 6: ``ValidatorChain.run`` returns the first rejection or accepts.

    Over any ordered list of validators (each deterministically accepting or
    rejecting) and any reading, the chain returns the result of the first
    rejecting validator; if every validator accepts, it returns an accepted
    result.

    Validates: Requirements FR-3b.2
    """
    validators: list[Validator] = [
        _StubValidator(accept=accept, name=f"v{index}")
        for index, accept in enumerate(decisions)
    ]
    chain = ValidatorChain(validators)
    reading = _make_reading()

    result = chain.run(reading)

    first_reject_index = next(
        (index for index, accept in enumerate(decisions) if not accept),
        None,
    )

    if first_reject_index is None:
        # Every validator accepted (including the empty-chain case).
        assert result.accepted is True
    else:
        # The chain must surface exactly the first rejecting validator's result.
        assert result.accepted is False
        assert result.validator_name == f"v{first_reject_index}"
        assert result.reason == f"rejected-by-v{first_reject_index}"


@given(mode=st.sampled_from(["valid", "no_sensor_contact"]))
def test_sensor_contact_validation_over_mock_adapter_modes(mode: str) -> None:
    """Property 4 driven via MockAdapter emission modes.

    ``VALID`` readings report ``sensor_contact=True`` (accepted); the
    ``NO_SENSOR_CONTACT`` mode reports ``sensor_contact=False`` (rejected).

    Validates: Requirements FR-3b.4
    """
    from vitals_on_fhir.adapters.builtin.mock import EmissionMode, MockAdapter

    emission_mode = (
        EmissionMode.VALID if mode == "valid" else EmissionMode.NO_SENSOR_CONTACT
    )
    reading = MockAdapter(emission_mode=emission_mode)._make_reading()

    result = SensorContactValidator().check(reading)

    assert result.accepted is (reading.sensor_contact is not False)


# Feature: hr-pipeline, Property 5: Duplicate validation rejects repeated readings
@given(
    triples=st.lists(
        st.tuples(
            st.text(min_size=1, max_size=8),
            st.integers(min_value=0, max_value=20),
            st.floats(min_value=20.0, max_value=250.0, allow_nan=False),
        ),
        min_size=1,
        max_size=40,
    )
)
def test_duplicate_validation_rejects_repeated_readings(
    triples: list[tuple[str, int, float]],
) -> None:
    """Property 5: ``DuplicateValidator`` accepts the first occurrence of each
    ``(device_id, effective, value)`` triple and rejects every repeat.

    Validates: Requirements FR-3b.5
    """
    from datetime import timedelta

    from vitals_on_fhir.validation.builtin.validators import DuplicateValidator

    validator = DuplicateValidator()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    seen: set[tuple[str, datetime, float]] = set()

    for device_id, effective_offset, value in triples:
        effective = base + timedelta(seconds=effective_offset)
        reading = HeartRate(
            effective=effective,
            device_id=device_id,
            value=value,
            sensor_contact=None,
        )
        key = (device_id, effective, value)
        expected_accepted = key not in seen

        result = validator.check(reading)

        assert result.accepted is expected_accepted
        assert result.validator_name == "duplicate"
        if expected_accepted:
            assert result.reason is None
        else:
            assert result.reason is not None
        seen.add(key)


# Feature: hr-pipeline, Property 4: Sensor-contact validation rejects only explicit loss
@given(sensor_contact=st.sampled_from([True, False, None]))
def test_sensor_contact_validation_rejects_only_explicit_loss(
    sensor_contact: bool | None,
) -> None:
    """Property 4: reject iff ``sensor_contact is False`` over True/False/None.

    Validates: Requirements FR-3b.4
    """
    reading = HeartRate(
        effective=datetime.now(tz=UTC),
        device_id="test-device",
        value=72.0,
        sensor_contact=sensor_contact,
    )

    result = SensorContactValidator().check(reading)

    assert result.accepted is (sensor_contact is not False)


# Feature: hr-pipeline, Property 3: Plausible-range validation matches the in-range predicate
@settings(max_examples=200)
@given(
    value=st.floats(
        min_value=-1000.0,
        max_value=1000.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    low=st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False),
    high=st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False),
)
def test_plausible_range_matches_in_range_predicate(
    value: float, low: float, high: float
) -> None:
    """Property 3: accept iff ``min <= value <= max`` for configured and default bounds.

    Two variants are checked against the same generated value:

    - Configured bounds: an explicit ``(low, high)`` pair passed to the
      constructor, ordered so ``low <= high`` regardless of generation order.
    - Default bounds: no override, so the validator falls back to the
      ``HeartRate.plausible_range`` class variable.

    Validates: Requirements FR-3b.3
    """
    hr_min, hr_max = (low, high) if low <= high else (high, low)
    reading = HeartRate(effective=datetime(2026, 1, 1, tzinfo=UTC), device_id="dev-1", value=value)

    configured = PlausibleRangeValidator(hr_min=hr_min, hr_max=hr_max)
    expected_configured = hr_min <= value <= hr_max
    assert configured.check(reading).accepted is expected_configured

    default = PlausibleRangeValidator()
    default_low, default_high = HeartRate.plausible_range
    expected_default = default_low <= value <= default_high
    assert default.check(reading).accepted is expected_default
