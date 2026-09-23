# SPDX-License-Identifier: AGPL-3.0-or-later
"""Metadata and instantiation tests for the concrete ``OxygenSaturation`` vital sign.

Covers the "every concrete vital-sign class has valid metadata" rule from
``testing.md`` for ``OxygenSaturation`` (a concrete ``ScalarVital``), plus the
``__init_subclass__`` metadata-enforcement contract and frozen-instance behavior.

Requirements: FR-SPO2-1, NFR-SPO2-1.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import ClassVar

import pytest

from vitals_on_fhir.vitals import OxygenSaturation, ScalarVital


def test_loinc_code_is_expected_spo2_code() -> None:
    """``loinc_code`` is the pulse-oximetry SpO2 LOINC code."""
    assert isinstance(OxygenSaturation.loinc_code, str)
    assert OxygenSaturation.loinc_code == "59408-5"


def test_us_core_profile_is_pulse_oximetry_url() -> None:
    """``us_core_profile`` is the US Core Pulse Oximetry canonical URL."""
    assert isinstance(OxygenSaturation.us_core_profile, str)
    assert OxygenSaturation.us_core_profile.startswith("http://hl7.org/fhir/")
    assert OxygenSaturation.us_core_profile == (
        "http://hl7.org/fhir/us/core/StructureDefinition/us-core-pulse-oximetry"
    )


def test_ucum_unit_is_percent() -> None:
    """``ucum_unit`` is the UCUM percent code."""
    assert isinstance(OxygenSaturation.ucum_unit, str)
    assert OxygenSaturation.ucum_unit == "%"


def test_plausible_range_is_ordered_float_pair() -> None:
    """``plausible_range`` is a ``(float, float)`` with ``range[0] < range[1]``."""
    plausible_range = OxygenSaturation.plausible_range
    assert isinstance(plausible_range, tuple)
    assert len(plausible_range) == 2
    low, high = plausible_range
    assert isinstance(low, float)
    assert isinstance(high, float)
    assert low < high
    assert (low, high) == (70.0, 100.0)


def test_instantiates_with_minimal_valid_arguments() -> None:
    """``OxygenSaturation`` constructs from a tz-aware effective, device_id, and value."""
    effective = datetime.now(UTC)
    spo2 = OxygenSaturation(effective=effective, device_id="device-1", value=98.0)

    assert spo2.effective is effective
    assert spo2.effective.tzinfo is not None
    assert spo2.device_id == "device-1"
    assert spo2.value == 98.0


def test_instance_is_frozen() -> None:
    """Instances are immutable: assigning to a field raises ``FrozenInstanceError``."""
    spo2 = OxygenSaturation(effective=datetime.now(UTC), device_id="device-1", value=98.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        spo2.value = 99.0  # type: ignore[misc]


def test_complete_subclass_is_accepted() -> None:
    """A concrete ``ScalarVital`` declaring all required metadata is accepted at definition."""

    @dataclasses.dataclass(frozen=True, kw_only=True)
    class CompleteVital(ScalarVital):
        loinc_code: ClassVar[str] = "12345-6"
        ucum_unit: ClassVar[str] = "%"
        us_core_profile: ClassVar[str] = "http://hl7.org/fhir/example"
        plausible_range: ClassVar[tuple[float, float]] = (0.0, 100.0)

    instance = CompleteVital(effective=datetime.now(UTC), device_id="d", value=1.0)
    assert instance.value == 1.0


def test_incomplete_subclass_raises_at_definition() -> None:
    """A concrete ``ScalarVital`` missing required metadata raises ``TypeError`` at import time."""
    with pytest.raises(TypeError):

        @dataclasses.dataclass(frozen=True, kw_only=True)
        class IncompleteVital(ScalarVital):
            # Assigns ``loinc_code`` (marking it concrete) but omits ``us_core_profile``.
            loinc_code: ClassVar[str] = "12345-6"
            ucum_unit: ClassVar[str] = "%"
            plausible_range: ClassVar[tuple[float, float]] = (0.0, 100.0)
