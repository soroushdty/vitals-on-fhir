# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validation wiring tests for the body-weight slice.

Covers the per-vital-class plausibility behavior the composition root relies on
(``PlausibleRangeValidator`` with a ``BodyWeight`` entry in its overrides map),
the ``INFO``-safe rejection reason, and duplicate detection for a body-weight
reading. No validator code changes in this slice; these tests pin the *wiring*
contract described in design §7.
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
from vitals_on_fhir.vitals.builtin.body_weight import BodyWeight
from vitals_on_fhir.vitals.builtin.heart_rate import HeartRate
from vitals_on_fhir.vitals.builtin.oxygen_saturation import OxygenSaturation

# The scalar vitals whose bounds the composition root wires into the per-vital
# overrides map, chosen so that cross-application would be observable: HR
# (20-250), SpO2 (70-100), and body weight (2-650).
_SCALAR_CLASSES: tuple[type[ScalarVital], ...] = (
    HeartRate,
    OxygenSaturation,
    BodyWeight,
)

_EFFECTIVE = datetime(2026, 1, 1, tzinfo=UTC)


def _reading(cls: type[ScalarVital], value: float) -> ScalarVital:
    """Build a minimal reading of *cls* with the given value."""
    return cls(effective=_EFFECTIVE, device_id="dev-1", value=value)


# Feature: weight-body-mass, Property 5: Per-class bounds applied with no cross-application
@settings(max_examples=200)
@given(
    override_choices=st.fixed_dictionaries(
        {
            cls: st.one_of(
                st.none(),
                st.tuples(
                    st.floats(
                        min_value=0.0,
                        max_value=700.0,
                        allow_nan=False,
                        allow_infinity=False,
                    ),
                    st.floats(
                        min_value=0.0,
                        max_value=700.0,
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
        max_value=800.0,
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
    when present, else its class ``plausible_range``. Acceptance is iff the value
    is within those bounds. A bound configured for one class (e.g. a weight
    override) never changes another class's decision.

    Validates: Requirements FR-WT-6
    """
    overrides: dict[type, tuple[float, float]] = {}
    for cls, pair in override_choices.items():
        if pair is not None:
            low, high = pair
            overrides[cls] = (low, high) if low <= high else (high, low)

    validator = PlausibleRangeValidator(overrides=overrides)
    reading = _reading(reading_class, value)

    expected_low, expected_high = overrides.get(reading_class, reading_class.plausible_range)
    expected_accepted = expected_low <= value <= expected_high

    result = validator.check(reading)

    assert result.accepted is expected_accepted
    assert result.validator_name == "plausible_range"


def test_weight_bounds_apply_to_weight_not_hr_or_spo2() -> None:
    """``VOF_WEIGHT_*`` bounds apply to ``BodyWeight`` and not to HR/SpO2.

    A weight override of (40.0, 120.0) accepts a 70.0 kg weight and rejects a
    900.0 kg weight, while heart rate and SpO2 remain judged against their own
    class ranges — the 40-120 window must not cross-apply.

    Validates: Requirements FR-WT-6
    """
    validator = PlausibleRangeValidator(overrides={BodyWeight: (40.0, 120.0)})

    # Weight judged against its override.
    assert validator.check(_reading(BodyWeight, 70.0)).accepted is True
    assert validator.check(_reading(BodyWeight, 900.0)).accepted is False

    # HR falls back to (20, 250): 200 accepted; the 40-120 weight window must
    # NOT apply (else 200 would be rejected).
    assert validator.check(_reading(HeartRate, 200.0)).accepted is True
    # SpO2 falls back to (70, 100): 98 accepted.
    assert validator.check(_reading(OxygenSaturation, 98.0)).accepted is True


def test_hr_and_spo2_bounds_do_not_apply_to_weight() -> None:
    """HR/SpO2 overrides do not cross-apply to ``BodyWeight`` (the reverse).

    With HR and SpO2 overrides configured but no weight entry, a body weight is
    judged against its own class range (2.0, 650.0), untouched by the HR or SpO2
    windows.

    Validates: Requirements FR-WT-6
    """
    validator = PlausibleRangeValidator(
        overrides={HeartRate: (40.0, 60.0), OxygenSaturation: (95.0, 100.0)}
    )

    # Weight uses its own class range (2, 650): 70 accepted, 900 rejected.
    assert validator.check(_reading(BodyWeight, 70.0)).accepted is True
    assert validator.check(_reading(BodyWeight, 900.0)).accepted is False
    # 200 kg is inside the weight range but outside both the HR (40-60) and SpO2
    # (95-100) windows: it must be accepted for weight, proving no cross-application.
    assert validator.check(_reading(BodyWeight, 200.0)).accepted is True


def test_rejection_reason_names_bounds_not_value() -> None:
    """The rejection reason names only the bounds, never the measurement value.

    NFR-WT-5 forbids measurement values in ``INFO``-and-above log messages; the
    rejection reason (logged at ``INFO``) must therefore name bounds only.

    Validates: Requirements NFR-WT-5
    """
    validator = PlausibleRangeValidator(overrides={BodyWeight: (40.0, 120.0)})

    result = validator.check(_reading(BodyWeight, 900.0))

    assert result.accepted is False
    assert result.reason is not None
    assert "40.0" in result.reason
    assert "120.0" in result.reason
    # The rejected measurement value must not leak into the reason.
    assert "900" not in result.reason


def test_body_weight_duplicate_is_rejected() -> None:
    """A ``BodyWeight`` duplicate on ``(device_id, effective, value)`` is rejected.

    The first occurrence of a weight reading is accepted; an identical triple
    seen again in the same session is rejected, and a reading differing in any of
    the three fields is accepted — reusing the scalar identity key with no change
    to ``DuplicateValidator``.

    Validates: Requirements FR-WT-6, NFR-WT-6
    """
    validator = DuplicateValidator()

    first = BodyWeight(effective=_EFFECTIVE, device_id="dev-1", value=70.0)
    assert validator.check(first).accepted is True

    # Exact same (device_id, effective, value) → duplicate, rejected.
    repeat = BodyWeight(effective=_EFFECTIVE, device_id="dev-1", value=70.0)
    rejected = validator.check(repeat)
    assert rejected.accepted is False
    assert rejected.validator_name == "duplicate"
    assert rejected.reason is not None

    # Differing in value → not a duplicate.
    assert (
        validator.check(BodyWeight(effective=_EFFECTIVE, device_id="dev-1", value=70.5)).accepted
        is True
    )
    # Differing in effective → not a duplicate.
    assert (
        validator.check(
            BodyWeight(
                effective=_EFFECTIVE + timedelta(seconds=1),
                device_id="dev-1",
                value=70.0,
            )
        ).accepted
        is True
    )
    # Differing in device_id → not a duplicate.
    assert (
        validator.check(BodyWeight(effective=_EFFECTIVE, device_id="dev-2", value=70.0)).accepted
        is True
    )
