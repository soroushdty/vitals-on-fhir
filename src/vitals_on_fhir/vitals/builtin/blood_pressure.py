# SPDX-License-Identifier: AGPL-3.0-or-later
"""Concrete ``BloodPressure`` vital-sign class conforming to the Bluetooth Blood Pressure Service.

``BloodPressure`` is the first concrete :class:`~vitals_on_fhir.vitals.ComponentVital`. It carries
a systolic and a diastolic value (both in ``mm[Hg]``) and maps to the US Core Blood Pressure
profile: a panel Observation (LOINC ``85354-9``) whose values live in two ``component`` entries,
systolic (LOINC ``8480-6``) and diastolic (LOINC ``8462-4``).

Mean arterial pressure is intentionally not modelled: it is device-derived rather than
independently measured. It can be added later as an additive third component without any change
to the ``ComponentVital`` contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from vitals_on_fhir.vitals.base import ComponentSpec, ComponentVital


@dataclass(frozen=True, kw_only=True)
class BloodPressure(ComponentVital):
    """A single blood-pressure measurement with systolic and diastolic components.

    Maps to the US Core Blood Pressure profile. Both components are expressed in
    ``mm[Hg]``. The default plausible ranges are deliberately wide plausibility
    bounds (not diagnostic ranges); they are overridable from configuration via
    ``VOF_BP_*`` by the component range validator.
    """

    loinc_code: ClassVar[str] = "85354-9"
    us_core_profile: ClassVar[str] = (
        "http://hl7.org/fhir/us/core/StructureDefinition/us-core-blood-pressure"
    )
    components: ClassVar[tuple[ComponentSpec, ...]] = (
        ComponentSpec(
            field_name="systolic",
            loinc_code="8480-6",
            ucum_unit="mm[Hg]",
            default_range=(50.0, 250.0),
        ),
        ComponentSpec(
            field_name="diastolic",
            loinc_code="8462-4",
            ucum_unit="mm[Hg]",
            default_range=(30.0, 150.0),
        ),
    )

    systolic: float
    """Systolic pressure in ``mm[Hg]``."""

    diastolic: float
    """Diastolic pressure in ``mm[Hg]``."""
