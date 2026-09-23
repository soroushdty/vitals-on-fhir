# SPDX-License-Identifier: AGPL-3.0-or-later
"""Concrete ``OxygenSaturation`` vital-sign class for standard-profile pulse oximetry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from vitals_on_fhir.vitals.base import ScalarVital


@dataclass(frozen=True, kw_only=True)
class OxygenSaturation(ScalarVital):
    """A single peripheral oxygen-saturation (SpO2) measurement as a percentage.

    Maps to LOINC ``59408-5`` ("Oxygen saturation in Arterial blood by Pulse
    oximetry") and conforms to the US Core Pulse Oximetry profile. A
    standard-profile home pulse oximeter reports only the SpO2 percentage over
    the Bluetooth PLX profile, so this is a scalar vital with a single ``value``
    and no sensor-contact concept.
    """

    loinc_code: ClassVar[str] = "59408-5"
    ucum_unit: ClassVar[str] = "%"
    us_core_profile: ClassVar[str] = (
        "http://hl7.org/fhir/us/core/StructureDefinition/us-core-pulse-oximetry"
    )
    plausible_range: ClassVar[tuple[float, float]] = (70.0, 100.0)
