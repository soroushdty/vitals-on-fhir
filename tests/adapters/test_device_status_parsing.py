# SPDX-License-Identifier: AGPL-3.0-or-later
"""Device-reported status bits in the blood-pressure and PLX parsers (issue #7, ADR-0005).

The expected bit meanings are restated here from the specifications rather than
imported from the parsers, so a wrong bit in a parser table fails a test:

- Blood Pressure Measurement, Measurement Status: GSS (2026-09-09) Table 3.55.
- PLX Measurement Status and Device and Sensor Status: PLXS v1.0.1 Tables 3.4 and 3.5.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vitals_on_fhir.adapters.bp_parser import BloodPressureMeasurementParser
from vitals_on_fhir.adapters.plx_parser import PlxContinuousMeasurementParser
from vitals_on_fhir.vitals import BloodPressure, DeviceIssue, OxygenSaturation

_NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
_TIMESTAMP = (2026).to_bytes(2, "little") + bytes([10, 6, 8, 30, 0])

# Bit -> issue for every bit that rejects. Bits not listed must yield no issue.
_BP_REJECTING = {
    0: DeviceIssue.BODY_MOVEMENT,
    1: DeviceIssue.CUFF_TOO_LOOSE,
    5: DeviceIssue.IMPROPER_POSITION,
}
# Accepted on purpose: 2 irregular pulse, 3-4 pulse-rate range; 6-15 reserved.

_PLX_MEASUREMENT_REJECTING = {
    5: DeviceIssue.MEASUREMENT_ONGOING,
    6: DeviceIssue.EARLY_ESTIMATE,
    9: DeviceIssue.DATA_FROM_STORAGE,
    10: DeviceIssue.DEMONSTRATION_DATA,
    11: DeviceIssue.TEST_DATA,
    12: DeviceIssue.CALIBRATION_ONGOING,
    13: DeviceIssue.MEASUREMENT_UNAVAILABLE,
    14: DeviceIssue.QUESTIONABLE_MEASUREMENT,
    15: DeviceIssue.INVALID_MEASUREMENT,
}
# Accepted: 0-4 reserved, 7 validated data, 8 fully qualified data.

_PLX_DEVICE_SENSOR_REJECTING = {
    1: DeviceIssue.EQUIPMENT_MALFUNCTION,
    2: DeviceIssue.SIGNAL_PROCESSING_IRREGULARITY,
    3: DeviceIssue.INADEQUATE_SIGNAL,
    4: DeviceIssue.POOR_SIGNAL,
    5: DeviceIssue.LOW_PERFUSION,
    6: DeviceIssue.ERRATIC_SIGNAL,
    7: DeviceIssue.NON_PULSATILE_SIGNAL,
    8: DeviceIssue.QUESTIONABLE_PULSE,
    9: DeviceIssue.SIGNAL_ANALYSIS_ONGOING,
    10: DeviceIssue.SENSOR_INTERFERENCE,
    11: DeviceIssue.SENSOR_UNCONNECTED,
    12: DeviceIssue.UNKNOWN_SENSOR,
    13: DeviceIssue.SENSOR_DISPLACED,
    14: DeviceIssue.SENSOR_MALFUNCTIONING,
    15: DeviceIssue.SENSOR_DISCONNECTED,
}
# Accepted: 0 extended display update ongoing; 16-23 reserved.


def _expected(bits: int, table: dict[int, DeviceIssue]) -> frozenset[DeviceIssue]:
    return frozenset(issue for bit, issue in table.items() if bits >> bit & 1)


def _bp(status: int | None, *, optional_fields: bool = True) -> BloodPressure:
    """Parse a BP payload; ``optional_fields`` puts a timestamp, pulse and user ID first."""
    flags = 0x10 if status is not None else 0
    if optional_fields:
        flags |= 0x02 | 0x04 | 0x08
    payload = bytes([flags]) + (120).to_bytes(2, "little") + (80).to_bytes(2, "little")
    payload += (93).to_bytes(2, "little")
    if optional_fields:
        payload += _TIMESTAMP + (72).to_bytes(2, "little") + bytes([1])
    if status is not None:
        payload += status.to_bytes(2, "little")
    reading = BloodPressureMeasurementParser("bp", now=lambda: _NOW, device_user_id=1).parse(
        payload
    )
    assert isinstance(reading, BloodPressure)
    return reading


def _spo2(
    measurement: int | None,
    device_sensor: int | None,
    *,
    fast: bool = False,
    slow: bool = False,
    pulse_amplitude: bool = False,
) -> OxygenSaturation:
    """Parse a PLX Continuous Measurement payload with the given optional fields."""
    flags = (
        (0x01 if fast else 0)
        | (0x02 if slow else 0)
        | (0x04 if measurement is not None else 0)
        | (0x08 if device_sensor is not None else 0)
        | (0x10 if pulse_amplitude else 0)
    )
    pair = (97).to_bytes(2, "little") + (60).to_bytes(2, "little")
    payload = bytes([flags]) + pair
    payload += pair if fast else b""
    payload += pair if slow else b""
    if measurement is not None:
        payload += measurement.to_bytes(2, "little")
    if device_sensor is not None:
        payload += device_sensor.to_bytes(3, "little")
    if pulse_amplitude:
        payload += (5).to_bytes(2, "little")
    reading = PlxContinuousMeasurementParser("spo2", now=lambda: _NOW).parse(payload)
    assert isinstance(reading, OxygenSaturation)
    return reading


@pytest.mark.parametrize("bit", range(16))
@pytest.mark.parametrize("optional_fields", [True, False])
def test_each_bp_measurement_status_bit(bit: int, optional_fields: bool) -> None:
    """Only body movement, cuff too loose and improper position become issues."""
    reading = _bp(1 << bit, optional_fields=optional_fields)
    assert reading.device_issues == _expected(1 << bit, _BP_REJECTING)


@pytest.mark.parametrize("bit", range(16))
def test_each_plx_measurement_status_bit(bit: int) -> None:
    """Each Measurement Status bit maps as PLXS Table 3.4 says."""
    reading = _spo2(1 << bit, None, fast=True, slow=True)
    assert reading.device_issues == _expected(1 << bit, _PLX_MEASUREMENT_REJECTING)


@pytest.mark.parametrize("bit", range(24))
def test_each_plx_device_and_sensor_status_bit(bit: int) -> None:
    """Each Device and Sensor Status bit maps as PLXS Table 3.5 says, after Measurement Status."""
    reading = _spo2(0, 1 << bit, fast=True, pulse_amplitude=True)
    assert reading.device_issues == _expected(1 << bit, _PLX_DEVICE_SENSOR_REJECTING)


def test_plx_device_and_sensor_status_without_measurement_status() -> None:
    """With no Measurement Status, the Device and Sensor Status field moves up two bytes."""
    reading = _spo2(None, 1 << 13, slow=True)
    assert reading.device_issues == {DeviceIssue.SENSOR_DISPLACED}


def test_absent_status_fields_mean_no_issues() -> None:
    """A device that sends no status behaves as before: no issues."""
    assert _bp(None).device_issues == frozenset()
    assert _spo2(None, None).device_issues == frozenset()


@given(status=st.integers(min_value=0, max_value=0xFFFF))
def test_bp_status_property(status: int) -> None:
    """For any Measurement Status value, the issues are exactly the rejecting bits set."""
    assert _bp(status).device_issues == _expected(status, _BP_REJECTING)


@given(
    measurement=st.integers(min_value=0, max_value=0xFFFF),
    device_sensor=st.integers(min_value=0, max_value=0xFFFFFF),
    fast=st.booleans(),
    slow=st.booleans(),
)
def test_plx_status_property(measurement: int, device_sensor: int, fast: bool, slow: bool) -> None:
    """For any pair of status values, the issues are the union of both tables' rejecting bits."""
    reading = _spo2(measurement, device_sensor, fast=fast, slow=slow, pulse_amplitude=True)
    assert reading.device_issues == _expected(measurement, _PLX_MEASUREMENT_REJECTING) | _expected(
        device_sensor, _PLX_DEVICE_SENSOR_REJECTING
    )
    assert reading.value == 97.0
