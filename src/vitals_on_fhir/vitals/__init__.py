# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public API for the ``vitals`` package — domain model for vital signs."""

from vitals_on_fhir.vitals.base import (
    ComponentVital,
    DeviceInfo,
    ScalarVital,
    VitalSign,
)
from vitals_on_fhir.vitals.builtin.heart_rate import HeartRate

__all__ = [
    # ABCs
    "VitalSign",
    "ScalarVital",
    "ComponentVital",
    # Concrete defaults
    "HeartRate",
    "DeviceInfo",
]
