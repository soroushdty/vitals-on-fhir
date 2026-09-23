# SPDX-License-Identifier: AGPL-3.0-or-later
"""Metadata and instantiation tests for the concrete ``BodyTemperature`` vital sign.

Covers the "every concrete vital-sign class has valid metadata" rule from
``testing.md`` for ``BodyTemperature`` (a concrete ``ScalarVital``), plus the
``__init_subclass__`` metadata-enforcement contract and frozen-instance behavior.

Requirements: FR-TEMP-1, NFR-TEMP-6.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import ClassVar

import pytest

from vitals_on_fhir.vitals import BodyTemperature, ScalarVital


def test_loinc_code_is_expected_body_temperature_code() -> None:
    """``loinc_code`` is the body-temperature LOINC code."""
    assert isinstance(BodyTemperature.loinc_code, str)
    assert BodyTemperature.loinc_code == "8310-5"


def test_us_core_profile_is_body_temperature_url() -> None:
    """``us_core_profile`` is the US Core Body Temperature canonical URL."""
    assert isinstance(BodyTemperature.us_core_profile, str)
    assert BodyTemperature.us_core_profile.startswith("http://hl7.org/fhir/")
    assert BodyTemperature.us_core_profile == (
        "http://hl7.org/fhir/us/core/StructureDefinition/us-core-body-temperature"
    )


def test_ucum_unit_is_celsius() -> None:
    """``ucum_unit`` is the UCUM degree-Celsius code."""
    assert isinstance(BodyTemperature.ucum_unit, str)
    assert BodyTemperature.ucum_unit == "Cel"


def test_plausible_range_is_ordered_float_pair() -> None:
    """``plausible_range`` is a ``(float, float)`` with ``range[0] < range[1]``."""
    plausible_range = BodyTemperature.plausible_range
    assert isinstance(plausible_range, tuple)
    assert len(plausible_range) == 2
    low, high = plausible_range
    assert isinstance(low, float)
    assert isinstance(high, float)
    assert low < high
    assert (low, high) == (10.0, 47.0)


def test_instantiates_with_minimal_valid_arguments() -> None:
    """``BodyTemperature`` constructs from a tz-aware effective, device_id, and value."""
    effective = datetime.now(UTC)
    temp = BodyTemperature(effective=effective, device_id="device-1", value=37.0)

    assert temp.effective is effective
    assert temp.effective.tzinfo is not None
    assert temp.device_id == "device-1"
    assert temp.value == 37.0


def test_instance_is_frozen() -> None:
    """Instances are immutable: assigning to a field raises ``FrozenInstanceError``."""
    temp = BodyTemperature(effective=datetime.now(UTC), device_id="device-1", value=37.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        temp.value = 38.0  # type: ignore[misc]


def test_complete_subclass_is_accepted() -> None:
    """A concrete ``ScalarVital`` declaring all required metadata is accepted at definition."""

    @dataclasses.dataclass(frozen=True, kw_only=True)
    class CompleteVital(ScalarVital):
        loinc_code: ClassVar[str] = "12345-6"
        ucum_unit: ClassVar[str] = "Cel"
        us_core_profile: ClassVar[str] = "http://hl7.org/fhir/example"
        plausible_range: ClassVar[tuple[float, float]] = (10.0, 47.0)

    instance = CompleteVital(effective=datetime.now(UTC), device_id="d", value=1.0)
    assert instance.value == 1.0


def test_incomplete_subclass_raises_at_definition() -> None:
    """A concrete ``ScalarVital`` missing required metadata raises ``TypeError`` at import time."""
    with pytest.raises(TypeError):

        @dataclasses.dataclass(frozen=True, kw_only=True)
        class IncompleteVital(ScalarVital):
            # Assigns ``loinc_code`` (marking it concrete) but omits ``us_core_profile``.
            loinc_code: ClassVar[str] = "12345-6"
            ucum_unit: ClassVar[str] = "Cel"
            plausible_range: ClassVar[tuple[float, float]] = (10.0, 47.0)
