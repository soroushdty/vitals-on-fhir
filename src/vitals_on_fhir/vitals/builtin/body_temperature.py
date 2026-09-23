# SPDX-License-Identifier: AGPL-3.0-or-later
"""Concrete ``BodyTemperature`` vital-sign class for standard-profile thermometry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from vitals_on_fhir.vitals.base import ScalarVital


@dataclass(frozen=True, kw_only=True)
class BodyTemperature(ScalarVital):
    """A single body-temperature measurement in degrees Celsius.

    Maps to LOINC ``8310-5`` ("Body temperature") and conforms to the US Core
    Body Temperature profile. A standard-profile Bluetooth Health Thermometer
    reports the temperature as a single scalar quantity, so this is a scalar
    vital with a single ``value`` in degrees Celsius (UCUM ``Cel``); a
    Fahrenheit reading is normalized to Celsius by the parser before the
    reading is constructed.

    The default ``plausible_range`` of ``(10.0, 47.0)`` °C is a
    physical-plausibility bound, not a clinical threshold: it rejects values
    that could not have come from a live human body while admitting every
    temperature a human body has been documented to reach and survive.
    """

    loinc_code: ClassVar[str] = "8310-5"
    ucum_unit: ClassVar[str] = "Cel"
    us_core_profile: ClassVar[str] = (
        "http://hl7.org/fhir/us/core/StructureDefinition/us-core-body-temperature"
    )
    plausible_range: ClassVar[tuple[float, float]] = (10.0, 47.0)
