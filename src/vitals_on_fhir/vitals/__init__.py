# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public API for the ``vitals`` package — domain model for vital signs."""

from vitals_on_fhir.vitals.base import (
    ComponentSpec,
    ComponentVital,
    DeviceInfo,
    ScalarVital,
    VitalSign,
)
from vitals_on_fhir.vitals.builtin.blood_pressure import BloodPressure
from vitals_on_fhir.vitals.builtin.body_temperature import BodyTemperature
from vitals_on_fhir.vitals.builtin.heart_rate import HeartRate
from vitals_on_fhir.vitals.builtin.oxygen_saturation import OxygenSaturation

__all__ = [
    # ABCs
    "VitalSign",
    "ScalarVital",
    "ComponentVital",
    # Concrete defaults
    "HeartRate",
    "BloodPressure",
    "OxygenSaturation",
    "BodyTemperature",
    "DeviceInfo",
    "ComponentSpec",
]
