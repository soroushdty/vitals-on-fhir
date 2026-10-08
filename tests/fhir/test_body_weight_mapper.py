# SPDX-License-Identifier: AGPL-3.0-or-later
"""Mapper tests for the body-weight slice.

Confirms that ``BodyWeight`` — a new ``ScalarVital`` — resolves to the existing
``ScalarVitalMapper`` through the MRO registry with **no new mapper code**, and
that the built Observation validates as US Core Body Weight (LOINC ``29463-7``,
UCUM ``kg``, vital-signs category, US Core Body Weight profile, status
``final``). Also asserts the existing ``HeartRate`` / ``OxygenSaturation`` /
``BodyTemperature`` → ``ScalarVitalMapper`` and ``BloodPressure`` →
``ComponentVitalMapper`` resolutions are unchanged.

FHIR validity is asserted via ``fhir.resources`` model construction (an invalid
resource raises), never by re-implementing validation — see ``testing.md``
"FHIR validation assertions".

Validates: Requirements FR-WT-5, NFR-WT-3.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from vitals_on_fhir.fhir import (
    ComponentVitalMapper,
    ScalarVitalMapper,
    default_mapper_registry,
)
from vitals_on_fhir.vitals import (
    BloodPressure,
    BodyTemperature,
    BodyWeight,
    HeartRate,
    OxygenSaturation,
    ScalarVital,
)

#: One registry for the whole module, so resolved mappers compare by identity.
_MAPPERS = default_mapper_registry()

# Timezone-aware datetimes spanning a range of offsets so the mapper's UTC
# conversion is exercised, not just naive-UTC inputs.
_aware_datetimes = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2100, 1, 1),
    timezones=st.timezones(),
)


# Feature: weight-body-mass, FR-WT-5: weight reuses the scalar mapper via the MRO
def test_body_weight_resolves_to_scalar_mapper() -> None:
    """``BodyWeight`` resolves to ``ScalarVitalMapper`` via the MRO registry.

    No mapper code or registration is added for body weight: as a ``ScalarVital``
    subclass it inherits the mapper registered for ``ScalarVital``.

    Validates: Requirements FR-WT-5, NFR-WT-1
    """
    scalar_mapper = _MAPPERS.resolve(ScalarVital)
    resolved = _MAPPERS.resolve(BodyWeight)

    assert isinstance(resolved, ScalarVitalMapper)
    # The very same instance the base resolves to — inherited via the MRO.
    assert resolved is scalar_mapper
    assert ScalarVital in BodyWeight.__mro__


# Feature: weight-body-mass, FR-WT-5 / NFR-WT-1: existing resolutions unchanged
def test_existing_mapper_resolutions_unchanged_after_weight() -> None:
    """Adding ``BodyWeight`` leaves the other mapper resolutions unchanged.

    ``HeartRate``, ``OxygenSaturation`` and ``BodyTemperature`` still resolve to
    ``ScalarVitalMapper`` and ``BloodPressure`` still resolves to
    ``ComponentVitalMapper``.

    Validates: Requirements FR-WT-5, NFR-WT-1
    """
    assert isinstance(_MAPPERS.resolve(HeartRate), ScalarVitalMapper)
    assert isinstance(_MAPPERS.resolve(OxygenSaturation), ScalarVitalMapper)
    assert isinstance(_MAPPERS.resolve(BodyTemperature), ScalarVitalMapper)
    assert isinstance(_MAPPERS.resolve(BloodPressure), ComponentVitalMapper)


# Feature: weight-body-mass, FR-WT-5 / NFR-WT-3: valid US Core Body Weight
@given(
    value=st.floats(
        min_value=2.0, max_value=650.0, allow_nan=False, allow_infinity=False
    ),
    effective=_aware_datetimes,
    issued=_aware_datetimes,
)
def test_mapper_produces_valid_body_weight_observation(
    value: float,
    effective: datetime,
    issued: datetime,
) -> None:
    """``ScalarVitalMapper`` maps ``BodyWeight`` to a valid US Core Observation.

    For any plausible weight reading, the mapper returns a ``fhir.resources``
    Observation that constructs without a validation error and carries the fields
    required by the US Core Body Weight profile: ``status == "final"``, LOINC
    ``29463-7``, the ``vital-signs`` category, the US Core Body Weight profile URL
    in ``meta.profile``, both timestamps present, and a ``valueQuantity`` whose
    UCUM ``code`` is ``kg``.

    Validates: Requirements FR-WT-5, NFR-WT-3
    """
    reading = BodyWeight(
        effective=effective,
        device_id="dev-weight",
        value=value,
    )

    # Construction is the FHIR validity check: an invalid resource raises here.
    observation = ScalarVitalMapper().to_observation(
        reading,
        "Patient/local-patient",
        "Device/weight-scale",
        issued,
    )

    assert observation.get_resource_type() == "Observation"
    assert observation.status == "final"

    # LOINC 29463-7 body-weight code.
    assert observation.code.coding[0].code == BodyWeight.loinc_code
    assert observation.code.coding[0].code == "29463-7"

    # Vital-signs category.
    assert observation.category[0].coding[0].code == "vital-signs"

    # US Core Body Weight profile URL in meta.profile.
    assert observation.meta is not None
    assert BodyWeight.us_core_profile in [
        str(profile) for profile in observation.meta.profile
    ]

    # Both timestamps present and ISO 8601 parseable.
    assert observation.effectiveDateTime is not None
    assert observation.issued is not None
    assert isinstance(
        datetime.fromisoformat(observation.effectiveDateTime.isoformat()), datetime
    )
    assert isinstance(datetime.fromisoformat(observation.issued.isoformat()), datetime)

    # valueQuantity: UCUM system, code and display are the kg unit; value kept.
    assert observation.valueQuantity.system == "http://unitsofmeasure.org"
    assert observation.valueQuantity.code == BodyWeight.ucum_unit
    assert observation.valueQuantity.code == "kg"
    assert observation.valueQuantity.unit == "kg"
    assert float(observation.valueQuantity.value) == value

    # Effective time round-trips to the same instant in UTC.
    assert observation.effectiveDateTime.astimezone(UTC) == effective.astimezone(UTC)
