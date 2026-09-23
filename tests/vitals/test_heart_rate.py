# SPDX-License-Identifier: AGPL-3.0-or-later
"""Metadata and instantiation tests for the concrete ``HeartRate`` vital sign.

Covers the "every concrete vital-sign class has valid metadata" rule from
``testing.md`` for ``HeartRate`` (a concrete ``ScalarVital``).

Requirements: FR-4, FR-13.
"""

from __future__ import annotations

from datetime import UTC, datetime

from vitals_on_fhir.vitals import HeartRate


def test_loinc_code_is_non_empty_string() -> None:
    """``loinc_code`` is a non-empty string equal to the heart-rate LOINC code."""
    assert isinstance(HeartRate.loinc_code, str)
    assert HeartRate.loinc_code
    assert HeartRate.loinc_code == "8867-4"


def test_us_core_profile_is_fhir_url() -> None:
    """``us_core_profile`` is a canonical HL7 FHIR URL."""
    assert isinstance(HeartRate.us_core_profile, str)
    assert HeartRate.us_core_profile.startswith("http://hl7.org/fhir/")


def test_ucum_unit_is_non_empty_string() -> None:
    """``ucum_unit`` is a non-empty string equal to beats-per-minute."""
    assert isinstance(HeartRate.ucum_unit, str)
    assert HeartRate.ucum_unit
    assert HeartRate.ucum_unit == "/min"


def test_plausible_range_is_ordered_float_pair() -> None:
    """``plausible_range`` is a ``(float, float)`` with ``range[0] < range[1]``."""
    plausible_range = HeartRate.plausible_range
    assert isinstance(plausible_range, tuple)
    assert len(plausible_range) == 2
    low, high = plausible_range
    assert isinstance(low, float)
    assert isinstance(high, float)
    assert low < high


def test_instantiates_with_minimal_valid_arguments() -> None:
    """``HeartRate`` constructs from a timezone-aware effective, device_id, and value."""
    effective = datetime.now(UTC)
    hr = HeartRate(effective=effective, device_id="device-1", value=72.0)

    assert hr.effective is effective
    assert hr.effective.tzinfo is not None
    assert hr.device_id == "device-1"
    assert hr.value == 72.0
    assert hr.sensor_contact is None
