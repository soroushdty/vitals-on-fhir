# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provenance markers: patient-generated and simulated data (ADR-0002).

Every Observation this project builds comes from a personal health device, so
the mappers add :data:`PHD_CATEGORY` next to the vital-signs category and set
``performer`` to the Patient.  Readings from a simulated device additionally
carry the :data:`HTEST_SECURITY_LABEL` security label (see :func:`mark_simulated`),
as does the simulated Device itself, so mock output can never be taken for a
real measurement.

Allowed imports: stdlib and ``fhir.resources`` (lazily).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fhir.resources.R4B.observation import Observation

#: Observation category from the HL7 Personal Health Device IG v2.0.0: "An
#: observation coming from a personal health device, either directly or via a
#: personal health gateway that maps the data received from the PHD into a FHIR
#: Observation resource."
PHD_CATEGORY: dict[str, object] = {
    "coding": [
        {
            "system": "http://hl7.org/fhir/uv/phd/CodeSystem/PhdObservationCategories",
            "code": "phd",
            "display": "PHD generated Observation",
        }
    ]
}

#: HL7 v3 ActReason ``HTEST`` ("test health data"), the FHIR R4 security label for
#: simulated or synthetic data that is not real production data.
HTEST_SECURITY_LABEL: dict[str, str] = {
    "system": "http://terminology.hl7.org/CodeSystem/v3-ActReason",
    "code": "HTEST",
    "display": "test health data",
}


def mark_simulated(observation: Observation) -> Observation:
    """Return a copy of *observation* labelled as simulated (``HTEST``).

    Applied by the orchestrator to every Observation from a simulated device,
    whichever mapper built it.  An existing ``HTEST`` label is not duplicated.

    Args:
        observation: The Observation built from a simulated reading.

    Returns:
        A validated copy whose ``meta.security`` includes :data:`HTEST_SECURITY_LABEL`.
    """
    from fhir.resources.R4B.observation import Observation

    data = observation.model_dump(mode="json", exclude_none=True)
    meta = data.setdefault("meta", {})
    security = meta.setdefault("security", [])
    if not any(
        label.get("system") == HTEST_SECURITY_LABEL["system"]
        and label.get("code") == HTEST_SECURITY_LABEL["code"]
        for label in security
    ):
        security.append(dict(HTEST_SECURITY_LABEL))
    return Observation.model_validate(data)
