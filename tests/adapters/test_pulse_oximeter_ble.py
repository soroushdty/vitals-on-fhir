# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract-suite wiring and structural tests for ``PulseOximeterBleAdapter``.

Runs the reusable ``DeviceAdapterContract`` against the PLX BLE adapter with the
module-level ``bleak`` check skipped (it is a BLE adapter). These are structural
checks only — no connection is attempted, so no hardware or ``bleak`` is needed.
The ``BleConnection`` behavior the adapter composes (state transitions,
drop-None, disconnect unblocking ``vitals()``, and a quiet interval while
connected not being a disconnection) is covered generically in
``test_ble_connection.py``.

Requirements: FR-SPO2-4, FR-SPO2-8, NFR-SPO2-5, NFR-SPO2-6.
"""

from __future__ import annotations

from tests.adapters.contract import DeviceAdapterContract
from vitals_on_fhir.adapters.builtin.pulse_oximeter_ble import (
    PLX_CONTINUOUS_MEASUREMENT_UUID,
    PULSE_OXIMETER_SERVICE_UUID,
    PulseOximeterBleAdapter,
)
from vitals_on_fhir.vitals import OxygenSaturation


class TestPulseOximeterBleAdapterContract(DeviceAdapterContract):
    """``PulseOximeterBleAdapter`` satisfies the ``DeviceAdapter`` contract (structural)."""

    adapter_cls = PulseOximeterBleAdapter
    requires_hardware = True  # composes BleConnection; skip the bleak static check

    def make_adapter(self) -> PulseOximeterBleAdapter:
        """Return a fresh, unconnected PLX BLE adapter for the contract checks."""
        return PulseOximeterBleAdapter()


def test_supported_vitals_is_oxygen_saturation() -> None:
    """The adapter declares it produces ``OxygenSaturation`` readings."""
    assert PulseOximeterBleAdapter.supported_vitals == (OxygenSaturation,)


def test_uuids_are_standard_pulse_oximeter_service() -> None:
    """The module declares the standard PLX service (0x1822) and measurement (0x2A5F) UUIDs."""
    assert PULSE_OXIMETER_SERVICE_UUID.startswith("00001822")
    assert PLX_CONTINUOUS_MEASUREMENT_UUID.startswith("00002a5f")


def test_device_info_is_vendor_neutral() -> None:
    """``device_info`` reports a vendor-neutral standard-profile device."""
    info = PulseOximeterBleAdapter().device_info
    assert info.model == "Pulse Oximeter"
    assert info.identifiers["profile"] == "org.bluetooth.service.pulse_oximeter"


def test_matches_accepts_any_prefiltered_advertisement() -> None:
    """``matches`` returns True (service-UUID scan filter is authoritative)."""
    adapter = PulseOximeterBleAdapter()

    class _Adv:
        name = "Some Pulse Oximeter"

    assert adapter.matches(_Adv()) is True
    assert adapter.matches(object()) is True
