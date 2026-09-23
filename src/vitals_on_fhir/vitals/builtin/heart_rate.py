# SPDX-License-Identifier: AGPL-3.0-or-later
"""Concrete ``HeartRate`` vital-sign class conforming to the Bluetooth Heart Rate Service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from vitals_on_fhir.vitals.base import ScalarVital


@dataclass(frozen=True, kw_only=True)
class HeartRate(ScalarVital):
    """A single heart-rate measurement in beats per minute.

    Maps to LOINC ``8867-4`` and conforms to the US Core Heart Rate profile.
    The ``sensor_contact`` field is populated from the BLE flags byte when the
    device reports sensor-contact status; ``None`` means the device does not
    report it.
    """

    loinc_code: ClassVar[str] = "8867-4"
    ucum_unit: ClassVar[str] = "/min"
    us_core_profile: ClassVar[str] = (
        "http://hl7.org/fhir/us/core/StructureDefinition/us-core-heart-rate"
    )
    plausible_range: ClassVar[tuple[float, float]] = (20.0, 250.0)

    sensor_contact: bool | None = None
    """Whether the sensor was in contact with skin at the time of measurement.

    - ``True`` — sensor contact confirmed.
    - ``False`` — sensor contact lost (reading should be rejected by ``SensorContactValidator``).
    - ``None`` — device does not report sensor contact (field is absent in BLE flags).
    """
