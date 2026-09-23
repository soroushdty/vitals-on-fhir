# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public API for the ``adapters`` package — device connectivity and payload parsing."""

from vitals_on_fhir.adapters.base import ConnectionState, DeviceAdapter
from vitals_on_fhir.adapters.ble import (
    BleConnection,
    BleHeartRateAdapter,
    GattCharacteristicParser,
)
from vitals_on_fhir.adapters.bp_parser import BloodPressureMeasurementParser
from vitals_on_fhir.adapters.builtin.blood_pressure_ble import BloodPressureBleAdapter
from vitals_on_fhir.adapters.builtin.miband10 import MiBand10Adapter
from vitals_on_fhir.adapters.builtin.mock import (
    BloodPressureEmissionMode,
    EmissionMode,
    MockAdapter,
    MockBloodPressureAdapter,
    MockOximeterAdapter,
    MockThermometerAdapter,
    OximeterEmissionMode,
    ThermometerEmissionMode,
)
from vitals_on_fhir.adapters.builtin.pulse_oximeter_ble import PulseOximeterBleAdapter
from vitals_on_fhir.adapters.builtin.thermometer_ble import HealthThermometerBleAdapter
from vitals_on_fhir.adapters.parser import HeartRateMeasurementParser

__all__ = [
    # ABCs
    "ConnectionState",
    "DeviceAdapter",
    "GattCharacteristicParser",
    "BleHeartRateAdapter",
    # Reusable building blocks
    "BleConnection",
    # Concrete defaults
    "HeartRateMeasurementParser",
    "BloodPressureMeasurementParser",
    "MiBand10Adapter",
    "BloodPressureBleAdapter",
    "MockAdapter",
    "EmissionMode",
    "MockBloodPressureAdapter",
    "BloodPressureEmissionMode",
    "PulseOximeterBleAdapter",
    "MockOximeterAdapter",
    "OximeterEmissionMode",
    "HealthThermometerBleAdapter",
    "MockThermometerAdapter",
    "ThermometerEmissionMode",
]
