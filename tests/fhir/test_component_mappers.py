# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the ComponentVitalMapper and component mapper registry resolution.

Covers the US Core Blood Pressure Observation shape (values in ``component``
entries, no panel ``valueQuantity``) and that the mapper registry dispatches
``BloodPressure`` to ``ComponentVitalMapper`` while ``HeartRate`` still resolves
to ``ScalarVitalMapper``.

Requirements: FR-HH-3, FR-HH-8, NFR-HH-3, NFR-HH-1.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from vitals_on_fhir.fhir import (
    ComponentVitalMapper,
    ScalarVitalMapper,
    resolve_mapper,
)
from vitals_on_fhir.vitals import BloodPressure, HeartRate

_PATIENT_REF = "Patient/local-patient"
_DEVICE_REF = "Device/blood-pressure-cuff"


def _bp() -> BloodPressure:
    """Build a representative blood-pressure reading."""
    return BloodPressure(
        effective=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        device_id="cuff-1",
        systolic=118.0,
        diastolic=76.0,
    )


def _map_bp() -> object:
    """Map a blood-pressure reading to an Observation via ComponentVitalMapper."""
    return ComponentVitalMapper().to_observation(
        _bp(), _PATIENT_REF, _DEVICE_REF, issued=datetime(2026, 1, 1, 12, 3, tzinfo=UTC)
    )


def test_blood_pressure_resolves_to_component_mapper() -> None:
    """``BloodPressure`` resolves to ``ComponentVitalMapper`` via the MRO."""
    resolved = resolve_mapper(BloodPressure)
    assert isinstance(resolved, ComponentVitalMapper)


def test_heart_rate_still_resolves_to_scalar_mapper() -> None:
    """``HeartRate`` still resolves to ``ScalarVitalMapper`` (scalar path unchanged)."""
    resolved = resolve_mapper(HeartRate)
    assert isinstance(resolved, ScalarVitalMapper)


def test_observation_is_valid_us_core_blood_pressure() -> None:
    """The mapped Observation constructs (FHIR-valid) with the US Core BP shape."""
    observation = _map_bp()

    assert observation.get_resource_type() == "Observation"
    assert observation.status == "final"
    assert observation.category[0].coding[0].code == "vital-signs"

    # Panel code is the blood-pressure LOINC 85354-9.
    assert observation.code.coding[0].code == "85354-9"

    # US Core Blood Pressure profile URL in meta.profile.
    assert observation.meta is not None
    assert BloodPressure.us_core_profile in [str(p) for p in observation.meta.profile]

    # Both timestamps present.
    assert observation.effectiveDateTime is not None
    assert observation.issued is not None

    # id parses as a UUID.
    assert isinstance(UUID(observation.id), UUID)


def test_values_live_in_components_not_panel() -> None:
    """Values are carried in ``component`` entries; there is no panel ``valueQuantity``."""
    observation = _map_bp()

    assert observation.valueQuantity is None
    assert observation.component is not None
    assert len(observation.component) == 2

    by_code = {c.code.coding[0].code: c for c in observation.component}
    assert set(by_code) == {"8480-6", "8462-4"}

    systolic = by_code["8480-6"]
    diastolic = by_code["8462-4"]
    assert float(systolic.valueQuantity.value) == 118.0
    assert float(diastolic.valueQuantity.value) == 76.0
    for component in (systolic, diastolic):
        assert component.valueQuantity.system == "http://unitsofmeasure.org"
        assert component.valueQuantity.code == "mm[Hg]"


def test_component_order_follows_declaration() -> None:
    """Component entries appear in the vital's declared order (systolic, diastolic)."""
    observation = _map_bp()
    codes = [c.code.coding[0].code for c in observation.component]
    assert codes == ["8480-6", "8462-4"]
