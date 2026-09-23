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
from vitals_on_fhir.vitals.base import ScalarVital, VitalSign

if TYPE_CHECKING:
    from fhir.resources.R4B.observation import Observation


# Fixed codings and systems mandated by fhir-conventions.md.
_LOINC_SYSTEM = "http://loinc.org"
_UCUM_SYSTEM = "http://unitsofmeasure.org"
_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/observation-category"

# Human-friendly display for the valueQuantity unit. The UCUM ``code`` remains
# authoritative (``ucum_unit``); this display is the friendly beats-per-minute
# label per the FHIR conventions.
_VALUE_UNIT_DISPLAY = "beats/minute"


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
                "unit": _VALUE_UNIT_DISPLAY,
                "system": _UCUM_SYSTEM,
                "code": vital_class.ucum_unit,
            },
        }
        return Observation.model_validate(data)


class ComponentVitalMapper(VitalMapper):
    """Maps a :class:`~vitals_on_fhir.vitals.ComponentVital` to a FHIR Observation.

    Roadmap stub — no concrete :class:`~vitals_on_fhir.vitals.ComponentVital`
    subclass exists in the MVP. Implement this when adding blood pressure or
    other multi-component vital signs.
    """

    def to_observation(
        self,
        vital: VitalSign,
        patient_ref: str,
        device_ref: str,
        issued: datetime,
    ) -> Observation:
        """Convert a :class:`~vitals_on_fhir.vitals.ComponentVital` to a FHIR Observation.

        Args:
            vital: A concrete :class:`~vitals_on_fhir.vitals.ComponentVital` instance.
            patient_ref: FHIR reference string for the subject Patient.
            device_ref: FHIR reference string for the source Device.
            issued: Timezone-aware processing timestamp.

        Returns:
            A ``fhir.resources.R4B.observation.Observation`` instance.

        Raises:
            NotImplementedError: Always — this is a roadmap stub with no MVP
                caller.
        """
        raise NotImplementedError(
            "ComponentVitalMapper is a roadmap stub; no MVP vital uses it."
        )
