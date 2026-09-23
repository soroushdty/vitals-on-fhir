# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the ScalarVitalMapper and the mapper registry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar
from uuid import UUID

from hypothesis import given, settings
from hypothesis import strategies as st

from vitals_on_fhir.fhir import (
    ComponentVitalMapper,
    ScalarVitalMapper,
    resolve_mapper,
)
from vitals_on_fhir.vitals import (
    BloodPressure,
    HeartRate,
    OxygenSaturation,
    ScalarVital,
)

# Feature: hr-pipeline, Property 9: Mapper resolves via the MRO
#
# An unregistered ScalarVital subclass carrying valid ClassVar metadata must
# resolve to the ScalarVitalMapper instance registered for ScalarVital (as a
# fhir-package-load side effect) via resolve_mapper's MRO walk — the subclass
# needs no mapper of its own.


@dataclass(frozen=True, kw_only=True)
class _UnregisteredScalarVital(ScalarVital):
    """A test-local ScalarVital subclass with valid metadata and no mapper."""

    loinc_code: ClassVar[str] = "99999-9"
    ucum_unit: ClassVar[str] = "/min"
    us_core_profile: ClassVar[str] = (
        "http://hl7.org/fhir/us/core/StructureDefinition/us-core-vital-signs"
    )
    plausible_range: ClassVar[tuple[float, float]] = (0.0, 500.0)


@dataclass(frozen=True, kw_only=True)
class _AnotherUnregisteredScalarVital(ScalarVital):
    """A second test-local ScalarVital subclass with different metadata."""

    loinc_code: ClassVar[str] = "12345-6"
    ucum_unit: ClassVar[str] = "mg/dL"
    us_core_profile: ClassVar[str] = (
        "http://hl7.org/fhir/us/core/StructureDefinition/us-core-observation-lab"
    )
    plausible_range: ClassVar[tuple[float, float]] = (10.0, 400.0)


# Feature: hr-pipeline, Property 9: Mapper resolves via the MRO
def test_unregistered_scalar_vital_resolves_to_scalar_mapper() -> None:
    """An unregistered ScalarVital subclass resolves to the ScalarVital mapper.

    Validates: Requirements FR-4.9
    """
    scalar_mapper = resolve_mapper(ScalarVital)
    assert isinstance(scalar_mapper, ScalarVitalMapper)

    # The subclass has no explicit registration, yet resolves to the very same
    # mapper instance registered for its ScalarVital base via the MRO walk.
    resolved = resolve_mapper(_UnregisteredScalarVital)
    assert isinstance(resolved, ScalarVitalMapper)
    assert resolved is scalar_mapper


# Feature: hr-pipeline, Property 9: Mapper resolves via the MRO
@given(
    vital_class=st.sampled_from(
        [_UnregisteredScalarVital, _AnotherUnregisteredScalarVital]
    )
)
def test_scalar_vital_subclasses_resolve_via_mro(
    vital_class: type[ScalarVital],
) -> None:
    """Every unregistered ScalarVital subclass resolves to the base's mapper.

    For any ScalarVital subclass carrying valid metadata and no explicit
    registration, resolve_mapper returns the mapper registered for ScalarVital.

    Validates: Requirements FR-4.9
    """
    base_mapper = resolve_mapper(ScalarVital)
    resolved = resolve_mapper(vital_class)

    assert isinstance(resolved, ScalarVitalMapper)
    # Same instance the base resolves to — inherited via the MRO, not re-created.
    assert resolved is base_mapper

    # ScalarVital appears in the subclass MRO, confirming inheritance is the
    # resolution path (the subclass itself is not registered).
    assert ScalarVital in vital_class.__mro__

    # Sanity: the resolved mapper produces an Observation from an instance built
    # entirely from the subclass's own metadata (no per-subclass mapper code).
    instance = vital_class(
        effective=datetime(2026, 1, 1, tzinfo=UTC),
        device_id="test-device",
        value=42.0,
    )
    observation = resolved.to_observation(
        instance,
        patient_ref="Patient/local-patient",
        device_ref="Device/test-device",
        issued=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert observation.get_resource_type() == "Observation"
    assert observation.code.coding[0].code == vital_class.loinc_code


# Feature: hr-pipeline, Property 8: Observation ids are unique
@given(
    values=st.lists(
        st.floats(
            min_value=20.0, max_value=250.0, allow_nan=False, allow_infinity=False
        ),
        min_size=1,
        max_size=50,
    )
)
def test_observation_ids_are_unique(values: list[float]) -> None:
    """Property 8: Observation ids are unique across a sequence of mapped readings.

    Mapping any sequence of ``HeartRate`` readings through ``ScalarVitalMapper``
    yields ``Observation`` resources whose ``id`` values are all distinct, even
    when the readings themselves are identical.

    Validates: Requirements FR-4.5
    """
    from vitals_on_fhir.vitals.builtin.heart_rate import HeartRate

    mapper = ScalarVitalMapper()
    issued = datetime(2026, 1, 1, tzinfo=UTC)
    effective = datetime(2026, 1, 1, tzinfo=UTC)

    ids = [
        mapper.to_observation(
            HeartRate(effective=effective, device_id="dev-1", value=value),
            "Patient/local-patient",
            "Device/mock-hr",
            issued,
        ).id
        for value in values
    ]

    assert len(ids) == len(set(ids))


# Timezone-aware datetimes spanning a range of offsets so the mapper's UTC
# conversion is exercised, not just naive-UTC inputs.
_aware_datetimes = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2100, 1, 1),
    timezones=st.timezones(),
)


# Feature: hr-pipeline, Property 7: Mapper produces a valid US Core Observation
@settings(max_examples=200)
@given(
    value=st.floats(
        min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False
    ),
    sensor_contact=st.sampled_from([True, False, None]),
    effective=_aware_datetimes,
    issued=_aware_datetimes,
    patient_id=st.text(
        alphabet=st.characters(min_codepoint=97, max_codepoint=122),
        min_size=1,
        max_size=32,
    ),
    device_slug=st.text(
        alphabet=st.characters(min_codepoint=97, max_codepoint=122),
        min_size=1,
        max_size=32,
    ),
)
def test_mapper_produces_valid_us_core_observation(
    value: float,
    sensor_contact: bool | None,
    effective: datetime,
    issued: datetime,
    patient_id: str,
    device_slug: str,
) -> None:
    """Property 7: ``ScalarVitalMapper.to_observation`` yields a valid US Core Observation.

    For any valid ``HeartRate`` reading and patient/device references, the
    mapper returns a ``fhir.resources`` Observation that constructs without a
    validation error and carries every field required by the US Core Heart Rate
    profile per the FHIR-validation checklist: ``resourceType == "Observation"``,
    ``status == "final"``, the LOINC ``8867-4`` code, the ``vital-signs``
    category, the US Core profile URL in ``meta.profile``, both
    ``effectiveDateTime`` and ``issued`` present and ISO 8601 parseable, and a
    ``valueQuantity`` with system ``http://unitsofmeasure.org`` and code
    ``/min``. FHIR validity is asserted via ``fhir.resources`` construction, not
    re-implemented.

    Validates: Requirements FR-4.1, FR-4.2, FR-4.3, FR-4.4, FR-4.5, FR-4.6,
    FR-4.7, NFR-4
    """
    from vitals_on_fhir.vitals.builtin.heart_rate import HeartRate

    patient_ref = f"Patient/{patient_id}"
    device_ref = f"Device/{device_slug}"
    reading = HeartRate(
        effective=effective,
        device_id="dev-1",
        value=value,
        sensor_contact=sensor_contact,
    )

    # Construction itself is the FHIR validity check: an invalid resource would
    # raise a pydantic ValidationError here.
    observation = ScalarVitalMapper().to_observation(
        reading, patient_ref, device_ref, issued
    )

    assert observation.get_resource_type() == "Observation"
    assert observation.status == "final"

    # LOINC 8867-4 heart-rate code.
    assert observation.code.coding[0].code == HeartRate.loinc_code
    assert observation.code.coding[0].code == "8867-4"

    # Vital-signs category.
    assert observation.category[0].coding[0].code == "vital-signs"

    # US Core profile URL in meta.profile.
    assert observation.meta is not None
    assert HeartRate.us_core_profile in [str(profile) for profile in observation.meta.profile]

    # Both timestamps present and ISO 8601 parseable.
    assert observation.effectiveDateTime is not None
    assert observation.issued is not None
    assert isinstance(
        datetime.fromisoformat(observation.effectiveDateTime.isoformat()), datetime
    )
    assert isinstance(datetime.fromisoformat(observation.issued.isoformat()), datetime)

    # Subject and device references.
    assert observation.subject.reference == patient_ref
    assert observation.device.reference == device_ref

    # valueQuantity: UCUM system and code, plus the reading's value.
    assert observation.valueQuantity.system == "http://unitsofmeasure.org"
    assert observation.valueQuantity.code == HeartRate.ucum_unit
    assert observation.valueQuantity.code == "/min"
    # unit display now derives from the vital's ucum_unit (was "beats/minute").
    assert observation.valueQuantity.unit == HeartRate.ucum_unit
    assert observation.valueQuantity.unit == "/min"
    assert float(observation.valueQuantity.value) == value

    # id parses as a UUID.
    assert isinstance(UUID(observation.id), UUID)

    # Effective time round-trips to the same instant in UTC.
    assert observation.effectiveDateTime.astimezone(UTC) == effective.astimezone(UTC)


# Feature: oxygen-saturation, FR-SPO2-5: SpO2 reuses the scalar mapper via the MRO
def test_oxygen_saturation_resolves_to_scalar_mapper() -> None:
    """``OxygenSaturation`` resolves to ``ScalarVitalMapper`` via the MRO registry.

    No mapper code or registration is added for SpO2: as a ``ScalarVital``
    subclass it inherits the mapper registered for ``ScalarVital``.

    Validates: Requirements FR-SPO2-5, NFR-SPO2-1
    """
    scalar_mapper = resolve_mapper(ScalarVital)
    resolved = resolve_mapper(OxygenSaturation)

    assert isinstance(resolved, ScalarVitalMapper)
    assert resolved is scalar_mapper
    assert ScalarVital in OxygenSaturation.__mro__


# Feature: oxygen-saturation, NFR-SPO2-1: existing resolutions unchanged
def test_existing_mapper_resolutions_unchanged() -> None:
    """``HeartRate`` and ``BloodPressure`` mapper resolution is unchanged.

    ``HeartRate`` still resolves to ``ScalarVitalMapper`` and ``BloodPressure``
    still resolves to ``ComponentVitalMapper`` after the SpO2 slice lands.

    Validates: Requirements FR-SPO2-5, NFR-SPO2-1
    """
    assert isinstance(resolve_mapper(HeartRate), ScalarVitalMapper)
    assert isinstance(resolve_mapper(BloodPressure), ComponentVitalMapper)


# Feature: oxygen-saturation, FR-SPO2-5 / NFR-SPO2-3: valid US Core Pulse Oximetry
@given(
    value=st.floats(
        min_value=70.0, max_value=100.0, allow_nan=False, allow_infinity=False
    ),
    effective=_aware_datetimes,
    issued=_aware_datetimes,
)
def test_mapper_produces_valid_pulse_oximetry_observation(
    value: float,
    effective: datetime,
    issued: datetime,
) -> None:
    """``ScalarVitalMapper`` maps ``OxygenSaturation`` to a valid US Core Observation.

    For any plausible SpO2 reading, the mapper returns a ``fhir.resources``
    Observation that constructs without a validation error and carries the
    fields required by the US Core Pulse Oximetry profile: ``status == "final"``,
    LOINC ``59408-5``, the ``vital-signs`` category, the US Core Pulse Oximetry
    profile URL in ``meta.profile``, both timestamps present, and a
    ``valueQuantity`` whose UCUM ``code`` and ``unit`` display are ``%``.

    Validates: Requirements FR-SPO2-5, NFR-SPO2-3
    """
    reading = OxygenSaturation(
        effective=effective,
        device_id="dev-spo2",
        value=value,
    )

    # Construction is the FHIR validity check: an invalid resource raises here.
    observation = ScalarVitalMapper().to_observation(
        reading,
        "Patient/local-patient",
        "Device/pulse-oximeter",
        issued,
    )

    assert observation.get_resource_type() == "Observation"
    assert observation.status == "final"

    # LOINC 59408-5 pulse-oximetry code.
    assert observation.code.coding[0].code == OxygenSaturation.loinc_code
    assert observation.code.coding[0].code == "59408-5"

    # Vital-signs category.
    assert observation.category[0].coding[0].code == "vital-signs"

    # US Core Pulse Oximetry profile URL in meta.profile.
    assert observation.meta is not None
    assert OxygenSaturation.us_core_profile in [
        str(profile) for profile in observation.meta.profile
    ]

    # Both timestamps present and ISO 8601 parseable.
    assert observation.effectiveDateTime is not None
    assert observation.issued is not None

    # valueQuantity: UCUM system, code and display are all the % unit; value kept.
    assert observation.valueQuantity.system == "http://unitsofmeasure.org"
    assert observation.valueQuantity.code == OxygenSaturation.ucum_unit
    assert observation.valueQuantity.code == "%"
    assert observation.valueQuantity.unit == "%"
    assert float(observation.valueQuantity.value) == value
