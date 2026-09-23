# SPDX-License-Identifier: AGPL-3.0-or-later
"""Metadata and instantiation tests for the concrete ``BloodPressure`` vital sign.

Covers the "every concrete vital-sign class has valid metadata" rule from
``testing.md`` for ``BloodPressure`` (the first concrete ``ComponentVital``).

Requirements: FR-HH-2, FR-HH-1.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from vitals_on_fhir.vitals import BloodPressure


def test_panel_loinc_code_is_blood_pressure() -> None:
    """``loinc_code`` is the blood-pressure panel LOINC code."""
    assert isinstance(BloodPressure.loinc_code, str)
    assert BloodPressure.loinc_code == "85354-9"


def test_us_core_profile_is_blood_pressure_profile() -> None:
    """``us_core_profile`` is the US Core Blood Pressure canonical URL."""
    assert BloodPressure.us_core_profile.startswith("http://hl7.org/fhir/")
    assert BloodPressure.us_core_profile.endswith("us-core-blood-pressure")


def test_components_are_systolic_then_diastolic() -> None:
    """``components`` declares systolic (8480-6) then diastolic (8462-4), both mm[Hg]."""
    components = BloodPressure.components
    assert len(components) == 2

    systolic, diastolic = components
    assert systolic.field_name == "systolic"
    assert systolic.loinc_code == "8480-6"
    assert diastolic.field_name == "diastolic"
    assert diastolic.loinc_code == "8462-4"
    assert all(spec.ucum_unit == "mm[Hg]" for spec in components)


def test_component_default_ranges_are_ordered_float_pairs() -> None:
    """Each component's ``default_range`` is a ``(float, float)`` with ``low < high``."""
    for spec in BloodPressure.components:
        low, high = spec.default_range
        assert isinstance(low, float)
        assert isinstance(high, float)
        assert low < high


def test_no_mean_arterial_pressure_component() -> None:
    """MAP is intentionally not modelled: only systolic and diastolic components exist."""
    field_names = {spec.field_name for spec in BloodPressure.components}
    assert field_names == {"systolic", "diastolic"}


def test_instantiates_with_minimal_valid_arguments() -> None:
    """``BloodPressure`` constructs from a tz-aware effective, device_id, and both values."""
    effective = datetime.now(UTC)
    bp = BloodPressure(effective=effective, device_id="cuff-1", systolic=118.0, diastolic=76.0)

    assert bp.effective is effective
    assert bp.effective.tzinfo is not None
    assert bp.device_id == "cuff-1"
    assert bp.systolic == 118.0
    assert bp.diastolic == 76.0


def test_component_values_reads_named_fields() -> None:
    """``component_values`` reads the named instance fields in declared order."""
    bp = BloodPressure(
        effective=datetime.now(UTC), device_id="cuff-1", systolic=118.0, diastolic=76.0
    )
    pairs = bp.component_values()

    assert [spec.field_name for spec, _ in pairs] == ["systolic", "diastolic"]
    assert [value for _, value in pairs] == [118.0, 76.0]


def test_instance_is_frozen() -> None:
    """``BloodPressure`` instances are immutable."""
    bp = BloodPressure(
        effective=datetime.now(UTC), device_id="cuff-1", systolic=118.0, diastolic=76.0
    )
    with pytest.raises(FrozenInstanceError):
        bp.systolic = 120.0  # type: ignore[misc]
