# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract-suite wiring and structural tests for ``BloodPressureBleAdapter``.

Runs the reusable ``DeviceAdapterContract`` against the BP BLE adapter with the
module-level ``bleak`` check skipped (it is a BLE adapter). These are structural
checks only — no connection is attempted, so no hardware or ``bleak`` is needed.

Requirements: FR-HH-4, FR-HH-9, NFR-HH-6.
"""

from __future__ import annotations

from tests.adapters.contract import DeviceAdapterContract
from vitals_on_fhir.adapters.builtin.blood_pressure_ble import (
    BLOOD_PRESSURE_MEASUREMENT_UUID,
    BLOOD_PRESSURE_SERVICE_UUID,
    BloodPressureBleAdapter,
)
from vitals_on_fhir.vitals import BloodPressure


class TestBloodPressureBleAdapterContract(DeviceAdapterContract):
    """``BloodPressureBleAdapter`` satisfies the ``DeviceAdapter`` contract (structural)."""

    adapter_cls = BloodPressureBleAdapter
    requires_hardware = True  # composes BleConnection; skip the bleak static check

    def make_adapter(self) -> BloodPressureBleAdapter:
        """Return a fresh, unconnected BP BLE adapter for the contract checks."""
        return BloodPressureBleAdapter()


def test_supported_vitals_is_blood_pressure() -> None:
    """The adapter declares it produces ``BloodPressure`` readings."""
    assert BloodPressureBleAdapter.supported_vitals == (BloodPressure,)


def test_uuids_are_standard_blood_pressure_service() -> None:
    """The module declares the standard BP service (0x1810) and measurement (0x2A35) UUIDs."""
    assert BLOOD_PRESSURE_SERVICE_UUID.startswith("00001810")
    assert BLOOD_PRESSURE_MEASUREMENT_UUID.startswith("00002a35")


def test_device_info_is_vendor_neutral() -> None:
    """``device_info`` reports a vendor-neutral standard-profile device."""
    info = BloodPressureBleAdapter().device_info
    assert info.model == "Blood Pressure Monitor"
    assert "profile" in info.identifiers


def test_matches_accepts_any_prefiltered_advertisement() -> None:
    """``matches`` returns True (service-UUID scan filter is authoritative)."""
    adapter = BloodPressureBleAdapter()

    class _Adv:
        name = "Some BP Cuff"

    assert adapter.matches(_Adv()) is True
    assert adapter.matches(object()) is True
