# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for ComponentRangeValidator and the component-aware DuplicateValidator.

Covers per-component range checking (defaults and config overrides), value-free
rejection reasons, pass-through of non-component vitals, and duplicate detection
for component vitals (the store-and-forward re-send guard).

Requirements: FR-HH-7, FR-HH-6, NFR-HH-5.
"""

from __future__ import annotations

from datetime import UTC, datetime

from vitals_on_fhir.validation.builtin.validators import (
    ComponentRangeValidator,
    DuplicateValidator,
)
from vitals_on_fhir.vitals import BloodPressure, HeartRate


def _bp(
    systolic: float = 118.0,
    diastolic: float = 76.0,
    *,
    when: datetime | None = None,
) -> BloodPressure:
    """Build a blood-pressure reading with the given values and effective time."""
    return BloodPressure(
        effective=when or datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        device_id="cuff-1",
        systolic=systolic,
        diastolic=diastolic,
    )


# --- ComponentRangeValidator --------------------------------------------------


def test_accepts_in_range_using_defaults() -> None:
    """A reading within each component's default range is accepted."""
    result = ComponentRangeValidator().check(_bp(118.0, 76.0))
    assert result.accepted is True


def test_rejects_systolic_above_default() -> None:
    """A systolic value above the default upper bound is rejected."""
    result = ComponentRangeValidator().check(_bp(300.0, 76.0))
    assert result.accepted is False
    assert "systolic" in (result.reason or "")


def test_rejects_diastolic_below_default() -> None:
    """A diastolic value below the default lower bound is rejected."""
    result = ComponentRangeValidator().check(_bp(118.0, 10.0))
    assert result.accepted is False
    assert "diastolic" in (result.reason or "")


def test_rejection_reason_omits_measurement_value() -> None:
    """The rejection reason names the component and bounds but not the value."""
    result = ComponentRangeValidator().check(_bp(300.0, 76.0))
    assert result.accepted is False
    assert "300" not in (result.reason or "")


def test_config_override_tightens_range() -> None:
    """A per-(class, field) override replaces the default bounds."""
    overrides = {(BloodPressure, "systolic"): (90.0, 120.0)}
    validator = ComponentRangeValidator(overrides)

    # 118 is inside the tightened band; 125 is outside it (but inside the default).
    assert validator.check(_bp(118.0, 76.0)).accepted is True
    rejected = validator.check(_bp(125.0, 76.0))
    assert rejected.accepted is False
    assert "systolic" in (rejected.reason or "")


def test_non_component_vital_passes_through() -> None:
    """A scalar vital (HeartRate) is accepted unchanged by the component validator."""
    hr = HeartRate(effective=datetime.now(tz=UTC), device_id="dev-1", value=72.0)
    assert ComponentRangeValidator().check(hr).accepted is True


# --- DuplicateValidator (component-aware) -------------------------------------


def test_duplicate_component_reading_rejected() -> None:
    """A second identical blood-pressure reading is rejected as a duplicate."""
    validator = DuplicateValidator()
    reading = _bp(118.0, 76.0)

    assert validator.check(reading).accepted is True
    assert validator.check(_bp(118.0, 76.0)).accepted is False


def test_distinct_component_readings_accepted() -> None:
    """Readings differing in a component value are not duplicates."""
    validator = DuplicateValidator()
    assert validator.check(_bp(118.0, 76.0)).accepted is True
    assert validator.check(_bp(119.0, 76.0)).accepted is True


def test_component_reading_differing_by_time_accepted() -> None:
    """Readings with the same values but different effective times are not duplicates."""
    validator = DuplicateValidator()
    first = _bp(118.0, 76.0, when=datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
    second = _bp(118.0, 76.0, when=datetime(2026, 1, 1, 12, 5, tzinfo=UTC))
    assert validator.check(first).accepted is True
    assert validator.check(second).accepted is True


def test_scalar_duplicate_detection_still_works() -> None:
    """Scalar duplicate detection is unchanged by the component generalization."""
    validator = DuplicateValidator()
    when = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    hr1 = HeartRate(effective=when, device_id="dev-1", value=72.0)
    hr2 = HeartRate(effective=when, device_id="dev-1", value=72.0)
    assert validator.check(hr1).accepted is True
    assert validator.check(hr2).accepted is False
