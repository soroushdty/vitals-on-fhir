# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validation wiring tests for the body-temperature slice.

Covers the per-vital-class plausibility behavior the composition root relies on
(``PlausibleRangeValidator`` with a ``BodyTemperature`` entry in its overrides
map), the ``INFO``-safe rejection reason, and duplicate detection for a
body-temperature reading. No validator code changes in this slice; these tests
pin the *wiring* contract described in design §7.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from vitals_on_fhir.validation.builtin.validators import (
    DuplicateValidator,
    PlausibleRangeValidator,
)
from vitals_on_fhir.vitals.base import ScalarVital
from vitals_on_fhir.vitals.builtin.body_temperature import BodyTemperature
from vitals_on_fhir.vitals.builtin.heart_rate import HeartRate
from vitals_on_fhir.vitals.builtin.oxygen_saturation import OxygenSaturation

# The three shipped scalar vitals whose bounds the composition root wires into
# the per-vital-class overrides map. Their class ``plausible_range`` values are
# deliberately disjoint enough that cross-application would be observable.
_SCALAR_CLASSES: tuple[type[ScalarVital], ...] = (
    HeartRate,
    OxygenSaturation,
    BodyTemperature,
)

_EFFECTIVE = datetime(2026, 1, 1, tzinfo=UTC)


def _reading(cls: type[ScalarVital], value: float) -> ScalarVital:
    """Build a minimal reading of *cls* with the given value."""
    return cls(effective=_EFFECTIVE, device_id="dev-1", value=value)


# Feature: body-temperature, Property 5: Per-class bounds applied with no cross-application
@settings(max_examples=200)
@given(
    # An overrides map: for each scalar class, optionally supply an override pair.
    override_choices=st.fixed_dictionaries(
        {
            cls: st.one_of(
                st.none(),
                st.tuples(
                    st.floats(
                        min_value=0.0,
                        max_value=500.0,
                        allow_nan=False,
                        allow_infinity=False,
                    ),
                    st.floats(
                        min_value=0.0,
                        max_value=500.0,
                        allow_nan=False,
                        allow_infinity=False,
                    ),
                ),
            )
            for cls in _SCALAR_CLASSES
        }
    ),
    reading_class=st.sampled_from(_SCALAR_CLASSES),
    value=st.floats(
        min_value=-100.0,
        max_value=600.0,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_per_class_bounds_no_cross_application(
    override_choices: dict[type[ScalarVital], tuple[float, float] | None],
    reading_class: type[ScalarVital],
    value: float,
) -> None:
    """Property 5: bounds applied are exactly the reading's own class bounds.

    For any overrides map and any scalar reading, the validator judges the
    reading against exactly that reading's own class bounds — its override entry
    when present, else its class ``plausible_range``. Acceptance is iff the
    value is within those bounds. A bound configured for one class (e.g. a
    temperature override) never changes another class's decision.

    Validates: Requirements FR-TEMP-6
    """
    # Normalize each generated pair so low <= high, matching how the composition
    # root supplies ordered (min, max) bounds.
    overrides: dict[type, tuple[float, float]] = {}
    for cls, pair in override_choices.items():
        if pair is not None:
            low, high = pair
            overrides[cls] = (low, high) if low <= high else (high, low)

    validator = PlausibleRangeValidator(overrides=overrides)
    reading = _reading(reading_class, value)

    # The bounds that SHOULD be applied: the reading's own class override if
    # present, else its class plausible_range — never another class's bounds.
    expected_low, expected_high = overrides.get(
        reading_class, reading_class.plausible_range
    )
    expected_accepted = expected_low <= value <= expected_high

    result = validator.check(reading)

    assert result.accepted is expected_accepted
    assert result.validator_name == "plausible_range"


def _bounds_below(cls: type[ScalarVital]) -> float:
    """Return a value strictly below *cls*'s class plausible range."""
    low, _ = cls.plausible_range
    return low - 1.0


def test_temp_bounds_apply_to_temperature_not_hr_or_spo2() -> None:
    """``VOF_TEMP_*`` bounds apply to ``BodyTemperature`` and not to HR/SpO2.

    A temperature override of (35.0, 39.0) accepts a 37.0 °C temperature and
    rejects a 60.0 °C temperature, while heart rate and SpO2 remain judged
    against their own class ranges — the 35–39 window must not cross-apply.

    Validates: Requirements FR-TEMP-6
    """
    validator = PlausibleRangeValidator(overrides={BodyTemperature: (35.0, 39.0)})

    # Temperature judged against its override.
    assert validator.check(_reading(BodyTemperature, 37.0)).accepted is True
    assert validator.check(_reading(BodyTemperature, 60.0)).accepted is False

    # HR falls back to (20, 250): 72 accepted; the 35-39 temperature window
    # must NOT apply (else 72 would be rejected).
    assert validator.check(_reading(HeartRate, 72.0)).accepted is True
    # SpO2 falls back to (70, 100): 98 accepted; 37 (inside the temp window)
    # must be rejected for SpO2 (it is below the SpO2 range), proving no
    # cross-application of the temperature bounds.
    assert validator.check(_reading(OxygenSaturation, 98.0)).accepted is True
    assert validator.check(_reading(OxygenSaturation, 37.0)).accepted is False


def test_hr_and_spo2_bounds_do_not_apply_to_temperature() -> None:
    """HR/SpO2 overrides do not cross-apply to ``BodyTemperature`` (the reverse).

    With HR and SpO2 overrides configured but no temperature entry, a body
    temperature is judged against its own class range (10.0, 47.0), untouched by
    the HR or SpO2 windows.

    Validates: Requirements FR-TEMP-6
    """
    validator = PlausibleRangeValidator(
        overrides={HeartRate: (40.0, 60.0), OxygenSaturation: (95.0, 100.0)}
    )

    # Temperature uses its own class range (10, 47): 37 accepted, 5 rejected.
    assert validator.check(_reading(BodyTemperature, 37.0)).accepted is True
    assert validator.check(_reading(BodyTemperature, 5.0)).accepted is False
    # 45 °C is inside the temperature range but outside both the HR (40-60 would
    # accept it, so use a temp-only value) — pick 12 °C, inside temp range,
    # outside HR and SpO2 windows: must be accepted for temperature.
    assert validator.check(_reading(BodyTemperature, 12.0)).accepted is True


def test_rejection_reason_names_bounds_not_value() -> None:
    """The rejection reason names only the bounds, never the measurement value.

    NFR-TEMP-5 forbids measurement values in ``INFO``-and-above log messages;
    the rejection reason (logged at ``INFO``) must therefore name bounds only.

    Validates: Requirements NFR-TEMP-5
    """
    validator = PlausibleRangeValidator(overrides={BodyTemperature: (35.0, 39.0)})

    result = validator.check(_reading(BodyTemperature, 60.0))

    assert result.accepted is False
    assert result.reason is not None
    assert "35.0" in result.reason
    assert "39.0" in result.reason
    # The rejected measurement value must not leak into the reason.
    assert "60" not in result.reason


def test_body_temperature_duplicate_is_rejected() -> None:
    """A ``BodyTemperature`` duplicate on ``(device_id, effective, value)`` is rejected.

    The first occurrence of a temperature reading is accepted; an identical
    triple seen again in the same session is rejected, and a reading differing
    in any of the three fields is accepted — reusing the scalar identity key
    with no change to ``DuplicateValidator``.

    Validates: Requirements FR-TEMP-6, NFR-TEMP-6
    """
    validator = DuplicateValidator()

    first = BodyTemperature(effective=_EFFECTIVE, device_id="dev-1", value=37.0)
    assert validator.check(first).accepted is True

    # Exact same (device_id, effective, value) → duplicate, rejected.
    repeat = BodyTemperature(effective=_EFFECTIVE, device_id="dev-1", value=37.0)
    rejected = validator.check(repeat)
    assert rejected.accepted is False
    assert rejected.validator_name == "duplicate"
    assert rejected.reason is not None

    # Differing in value → not a duplicate.
    assert (
        validator.check(
            BodyTemperature(effective=_EFFECTIVE, device_id="dev-1", value=37.5)
        ).accepted
        is True
    )
    # Differing in effective → not a duplicate.
    assert (
        validator.check(
            BodyTemperature(
                effective=_EFFECTIVE + timedelta(seconds=1),
                device_id="dev-1",
                value=37.0,
            )
        ).accepted
        is True
    )
    # Differing in device_id → not a duplicate.
    assert (
        validator.check(
            BodyTemperature(effective=_EFFECTIVE, device_id="dev-2", value=37.0)
        ).accepted
        is True
    )
