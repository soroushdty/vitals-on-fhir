# SPDX-License-Identifier: AGPL-3.0-or-later
"""Concrete VitalMapper implementations.

``ScalarVitalMapper`` handles any :class:`~vitals_on_fhir.vitals.ScalarVital`
subclass by reading its class-level LOINC / UCUM / profile metadata; no
mapper subclass is needed when adding a new scalar vital sign.

``ComponentVitalMapper`` is a roadmap-ready stub for multi-component vitals
(e.g. blood pressure). No concrete vital uses it in the MVP.

Observations target **FHIR R4 (4.0.1)** semantics and are built with the
R4B-compatible models under ``fhir.resources.R4B``. ``fhir.resources`` is
imported lazily inside method bodies; at module level its types are guarded by
``TYPE_CHECKING``. Resources are built with ``model_validate`` so pydantic
validation runs at construction time — a ``ValidationError`` propagates to the
caller (the orchestrator) rather than yielding an invalid resource.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from vitals_on_fhir.fhir.base import VitalMapper
from vitals_on_fhir.vitals.base import ComponentVital, ScalarVital, VitalSign

if TYPE_CHECKING:
    from fhir.resources.R4B.observation import Observation


# Fixed codings and systems mandated by fhir-conventions.md.
_LOINC_SYSTEM = "http://loinc.org"
_UCUM_SYSTEM = "http://unitsofmeasure.org"
_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/observation-category"


def _to_utc_isoformat(moment: datetime) -> str:
    """Return *moment* as an ISO 8601 string in UTC.

    Timezone-aware inputs are converted to UTC; the ``effective`` and ``issued``
    timestamps are required to be timezone-aware by the domain model, so this
    keeps the serialized instant unambiguous.

    Args:
        moment: A timezone-aware datetime.

    Returns:
        The instant formatted as an ISO 8601 string in UTC.
    """
    return moment.astimezone(UTC).isoformat()


class ScalarVitalMapper(VitalMapper):
    """Maps a :class:`~vitals_on_fhir.vitals.ScalarVital` to a FHIR Observation.

    Builds the Observation entirely from the vital sign's class metadata
    (``loinc_code``, ``ucum_unit``, ``us_core_profile``), so adding a new
    scalar vital sign type requires no mapper code.
    """

    def to_observation(
        self,
        vital: VitalSign,
        patient_ref: str,
        device_ref: str,
        issued: datetime,
    ) -> Observation:
        """Convert a :class:`~vitals_on_fhir.vitals.ScalarVital` to a FHIR Observation.

        The resulting Observation conforms to the US Core vital-signs profile
        declared on the vital's class. Every field is derived from class
        metadata or the supplied references, so a new ``ScalarVital`` subclass
        needs no mapper code.

        Args:
            vital: A concrete :class:`~vitals_on_fhir.vitals.ScalarVital` instance.
            patient_ref: FHIR reference string for the subject Patient
                (e.g. ``"Patient/local-patient"``).
            device_ref: FHIR reference string for the source Device
                (e.g. ``"Device/smart-band-10"``).
            issued: Timezone-aware processing timestamp for the ``issued`` field.

        Returns:
            A ``fhir.resources.R4B.observation.Observation`` instance conforming
            to the US Core vital-signs profile for the given vital-sign type.

        Raises:
            TypeError: If *vital* is not a :class:`ScalarVital`.
        """
        from fhir.resources.R4B.observation import Observation

        if not isinstance(vital, ScalarVital):
            raise TypeError(
                f"ScalarVitalMapper requires a ScalarVital, got {type(vital).__qualname__}."
            )

        vital_class = type(vital)
        data: dict[str, object] = {
            "id": str(uuid.uuid4()),
            "meta": {"profile": [vital_class.us_core_profile]},
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": _CATEGORY_SYSTEM,
                            "code": "vital-signs",
                            "display": "Vital Signs",
                        }
                    ]
                }
            ],
            "code": {
                "coding": [
                    {
                        "system": _LOINC_SYSTEM,
                        "code": vital_class.loinc_code,
                    }
                ]
            },
            "subject": {"reference": patient_ref},
            "device": {"reference": device_ref},
            "effectiveDateTime": _to_utc_isoformat(vital.effective),
            "issued": _to_utc_isoformat(issued),
            "valueQuantity": {
                "value": vital.value,
                "unit": vital_class.ucum_unit,
                "system": _UCUM_SYSTEM,
                "code": vital_class.ucum_unit,
            },
        }
        return Observation.model_validate(data)


class ComponentVitalMapper(VitalMapper):
    """Maps a :class:`~vitals_on_fhir.vitals.ComponentVital` to a FHIR Observation.

    Builds a panel Observation whose measured values live in ``component``
    entries — one per :class:`~vitals_on_fhir.vitals.ComponentSpec` declared on
    the vital's class — with no panel-level ``valueQuantity``. This matches the
    US Core Blood Pressure profile shape and generalizes to any multi-component
    vital, so a new ``ComponentVital`` subclass with correct metadata needs no
    mapper code.
    """

    def to_observation(
        self,
        vital: VitalSign,
        patient_ref: str,
        device_ref: str,
        issued: datetime,
    ) -> Observation:
        """Convert a :class:`~vitals_on_fhir.vitals.ComponentVital` to a FHIR Observation.

        The resulting Observation conforms to the US Core profile declared on the
        vital's class. The panel ``code`` is the vital's ``loinc_code``; each
        declared component becomes a ``component`` entry with its own LOINC code
        and a ``valueQuantity`` carrying the UCUM unit and value. No panel-level
        ``valueQuantity`` is set.

        Args:
            vital: A concrete :class:`~vitals_on_fhir.vitals.ComponentVital` instance.
            patient_ref: FHIR reference string for the subject Patient
                (e.g. ``"Patient/local-patient"``).
            device_ref: FHIR reference string for the source Device
                (e.g. ``"Device/blood-pressure-cuff"``).
            issued: Timezone-aware processing timestamp for the ``issued`` field.

        Returns:
            A ``fhir.resources.R4B.observation.Observation`` instance conforming
            to the US Core profile for the given component vital-sign type.

        Raises:
            TypeError: If *vital* is not a :class:`ComponentVital`.
        """
        from fhir.resources.R4B.observation import Observation

        if not isinstance(vital, ComponentVital):
            raise TypeError(
                f"ComponentVitalMapper requires a ComponentVital, "
                f"got {type(vital).__qualname__}."
            )

        vital_class = type(vital)
        components = [
            {
                "code": {
                    "coding": [
                        {
                            "system": _LOINC_SYSTEM,
                            "code": spec.loinc_code,
                        }
                    ]
                },
                "valueQuantity": {
                    "value": value,
                    "unit": spec.ucum_unit,
                    "system": _UCUM_SYSTEM,
                    "code": spec.ucum_unit,
                },
            }
            for spec, value in vital.component_values()
        ]
        data: dict[str, object] = {
            "id": str(uuid.uuid4()),
            "meta": {"profile": [vital_class.us_core_profile]},
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": _CATEGORY_SYSTEM,
                            "code": "vital-signs",
                            "display": "Vital Signs",
                        }
                    ]
                }
            ],
            "code": {
                "coding": [
                    {
                        "system": _LOINC_SYSTEM,
                        "code": vital_class.loinc_code,
                    }
                ]
            },
            "subject": {"reference": patient_ref},
            "device": {"reference": device_ref},
            "effectiveDateTime": _to_utc_isoformat(vital.effective),
            "issued": _to_utc_isoformat(issued),
            "component": components,
        }
        return Observation.model_validate(data)
