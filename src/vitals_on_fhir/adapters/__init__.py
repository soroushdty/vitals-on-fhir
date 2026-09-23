# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public API for the ``adapters`` package — device connectivity and payload parsing."""

from vitals_on_fhir.adapters.base import ConnectionState, DeviceAdapter
from vitals_on_fhir.adapters.ble import BleHeartRateAdapter, GattCharacteristicParser
from vitals_on_fhir.adapters.builtin.miband10 import MiBand10Adapter
from vitals_on_fhir.adapters.builtin.mock import EmissionMode, MockAdapter
from vitals_on_fhir.adapters.parser import HeartRateMeasurementParser

__all__ = [
    # ABCs
    "ConnectionState",
    "DeviceAdapter",
    "GattCharacteristicParser",
    "BleHeartRateAdapter",
    # Concrete defaults
    "HeartRateMeasurementParser",
    "MiBand10Adapter",
    "MockAdapter",
    "EmissionMode",
]
