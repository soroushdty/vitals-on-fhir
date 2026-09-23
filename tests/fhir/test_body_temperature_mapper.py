# SPDX-License-Identifier: AGPL-3.0-or-later
"""Mapper tests for the body-temperature slice (task 8.2).

Confirms that ``BodyTemperature`` — a new ``ScalarVital`` — resolves to the
existing ``ScalarVitalMapper`` through the MRO registry with **no new mapper
code**, and that the built Observation validates as US Core Body Temperature
(LOINC ``8310-5``, UCUM ``Cel``, vital-signs category, US Core Body Temperature
profile, status ``final``). Also asserts the existing ``HeartRate`` /
``OxygenSaturation`` → ``ScalarVitalMapper`` and ``BloodPressure`` →
``ComponentVitalMapper`` resolutions are unchanged.

FHIR validity is asserted via ``fhir.resources`` model construction (an invalid
resource raises), never by re-implementing validation — see ``testing.md``
"FHIR validation assertions".

Validates: Requirements FR-TEMP-5, NFR-TEMP-3.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from vitals_on_fhir.fhir import (
    ComponentVitalMapper,
    ScalarVitalMapper,
    resolve_mapper,
)
from vitals_on_fhir.vitals import (
    BloodPressure,
    BodyTemperature,
    HeartRate,
    OxygenSaturation,
    ScalarVital,
)

# Timezone-aware datetimes spanning a range of offsets so the mapper's UTC
# conversion is exercised, not just naive-UTC inputs.
_aware_datetimes = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2100, 1, 1),
    timezones=st.timezones(),
)


# Feature: body-temperature, FR-TEMP-5: temperature reuses the scalar mapper via the MRO
def test_body_temperature_resolves_to_scalar_mapper() -> None:
    """``BodyTemperature`` resolves to ``ScalarVitalMapper`` via the MRO registry.

    No mapper code or registration is added for body temperature: as a
    ``ScalarVital`` subclass it inherits the mapper registered for
    ``ScalarVital``.

    Validates: Requirements FR-TEMP-5, NFR-TEMP-1
    """
    scalar_mapper = resolve_mapper(ScalarVital)
    resolved = resolve_mapper(BodyTemperature)

    assert isinstance(resolved, ScalarVitalMapper)
    # The very same instance the base resolves to — inherited via the MRO.
    assert resolved is scalar_mapper
    assert ScalarVital in BodyTemperature.__mro__


# Feature: body-temperature, FR-TEMP-5 / NFR-TEMP-1: existing resolutions unchanged
def test_existing_mapper_resolutions_unchanged_after_temperature() -> None:
    """Adding ``BodyTemperature`` leaves the other mapper resolutions unchanged.

    ``HeartRate`` and ``OxygenSaturation`` still resolve to ``ScalarVitalMapper``
    and ``BloodPressure`` still resolves to ``ComponentVitalMapper``.

    Validates: Requirements FR-TEMP-5, NFR-TEMP-1
    """
    assert isinstance(resolve_mapper(HeartRate), ScalarVitalMapper)
    assert isinstance(resolve_mapper(OxygenSaturation), ScalarVitalMapper)
    assert isinstance(resolve_mapper(BloodPressure), ComponentVitalMapper)


# Feature: body-temperature, FR-TEMP-5 / NFR-TEMP-3: valid US Core Body Temperature
@given(
    value=st.floats(
        min_value=10.0, max_value=47.0, allow_nan=False, allow_infinity=False
    ),
    effective=_aware_datetimes,
    issued=_aware_datetimes,
)
def test_mapper_produces_valid_body_temperature_observation(
    value: float,
    effective: datetime,
    issued: datetime,
) -> None:
    """``ScalarVitalMapper`` maps ``BodyTemperature`` to a valid US Core Observation.

    For any plausible temperature reading, the mapper returns a
    ``fhir.resources`` Observation that constructs without a validation error
    and carries the fields required by the US Core Body Temperature profile:
    ``status == "final"``, LOINC ``8310-5``, the ``vital-signs`` category, the
    US Core Body Temperature profile URL in ``meta.profile``, both timestamps
    present, and a ``valueQuantity`` whose UCUM ``code`` is ``Cel``.

    Validates: Requirements FR-TEMP-5, NFR-TEMP-3
    """
    reading = BodyTemperature(
        effective=effective,
        device_id="dev-temp",
        value=value,
    )

    # Construction is the FHIR validity check: an invalid resource raises here.
    observation = ScalarVitalMapper().to_observation(
        reading,
        "Patient/local-patient",
        "Device/health-thermometer",
        issued,
    )

    assert observation.get_resource_type() == "Observation"
    assert observation.status == "final"

    # LOINC 8310-5 body-temperature code.
    assert observation.code.coding[0].code == BodyTemperature.loinc_code
    assert observation.code.coding[0].code == "8310-5"

    # Vital-signs category.
    assert observation.category[0].coding[0].code == "vital-signs"

    # US Core Body Temperature profile URL in meta.profile.
    assert observation.meta is not None
    assert BodyTemperature.us_core_profile in [
        str(profile) for profile in observation.meta.profile
    ]

    # Both timestamps present and ISO 8601 parseable.
    assert observation.effectiveDateTime is not None
    assert observation.issued is not None
    assert isinstance(
        datetime.fromisoformat(observation.effectiveDateTime.isoformat()), datetime
    )
    assert isinstance(datetime.fromisoformat(observation.issued.isoformat()), datetime)

    # valueQuantity: UCUM system, code and display are the Cel unit; value kept.
    assert observation.valueQuantity.system == "http://unitsofmeasure.org"
    assert observation.valueQuantity.code == BodyTemperature.ucum_unit
    assert observation.valueQuantity.code == "Cel"
    assert observation.valueQuantity.unit == "Cel"
    assert float(observation.valueQuantity.value) == value

    # Effective time round-trips to the same instant in UTC.
    assert observation.effectiveDateTime.astimezone(UTC) == effective.astimezone(UTC)
