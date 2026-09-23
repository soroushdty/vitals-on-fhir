# SPDX-License-Identifier: AGPL-3.0-or-later
"""Example tests for the Heart Rate Measurement parser (GATT 0x2A37).

Each valid fixture payload from ``conftest.py`` is asserted to parse into a
``HeartRate`` with the expected ``value`` and ``sensor_contact``. Truncated and
empty payloads must be dropped (parser returns ``None``).

Covers requirements FR-3a.1 (value-format decoding), FR-3a.2 (sensor-contact
tri-state), FR-3a.3 (field-offset accounting with RR intervals), and FR-3a.4
(malformed payloads return ``None``).
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from vitals_on_fhir.adapters.parser import HeartRateMeasurementParser
from vitals_on_fhir.vitals.builtin.heart_rate import HeartRate

_DEVICE_ID = "test-device"


def _parser() -> HeartRateMeasurementParser:
    """Build a parser bound to a fixed device id for deterministic tests."""
    return HeartRateMeasurementParser(_DEVICE_ID)


def test_uint8_contact(hr_payload_uint8_contact: bytes) -> None:
    """A uint8 payload with sensor contact detected decodes value and contact=True."""
    result = _parser().parse(hr_payload_uint8_contact)
    assert isinstance(result, HeartRate)
    assert result.value == 72.0
    assert result.sensor_contact is True
    assert result.device_id == _DEVICE_ID


def test_uint8_no_contact(hr_payload_uint8_no_contact: bytes) -> None:
    """A uint8 payload with sensor contact supported but not detected has contact=False."""
    result = _parser().parse(hr_payload_uint8_no_contact)
    assert isinstance(result, HeartRate)
    assert result.value == 80.0
    assert result.sensor_contact is False


def test_uint16_contact(hr_payload_uint16_contact: bytes) -> None:
    """A uint16 payload decodes the little-endian value and contact=True."""
    result = _parser().parse(hr_payload_uint16_contact)
    assert isinstance(result, HeartRate)
    assert result.value == 300.0
    assert result.sensor_contact is True


def test_uint16_no_contact(hr_payload_uint16_no_contact: bytes) -> None:
    """A uint16 payload with contact supported but not detected has contact=False."""
    result = _parser().parse(hr_payload_uint16_no_contact)
    assert isinstance(result, HeartRate)
    assert result.value == 310.0
    assert result.sensor_contact is False


def test_with_rr_intervals(hr_payload_with_rr: bytes) -> None:
    """RR-interval tail bytes do not affect the decoded heart-rate value or contact."""
    result = _parser().parse(hr_payload_with_rr)
    assert isinstance(result, HeartRate)
    assert result.value == 65.0
    assert result.sensor_contact is True


def test_truncated_returns_none(hr_payload_truncated: bytes) -> None:
    """A payload too short for its declared uint16 format is dropped (None)."""
    assert _parser().parse(hr_payload_truncated) is None


def test_empty_returns_none(hr_payload_empty: bytes) -> None:
    """A zero-length payload is dropped (None)."""
    assert _parser().parse(hr_payload_empty) is None


# Feature: hr-pipeline, Property 2: Parser never crashes on arbitrary bytes
# Validates: Requirements FR-3a.4
@settings(max_examples=200)
@given(data=st.binary())
def test_parser_never_crashes_on_arbitrary_bytes(data: bytes) -> None:
    """The parser tolerates any byte string: it returns ``None`` or a valid
    ``HeartRate`` and never raises for arbitrary input (empty, single-byte, and
    very long payloads included)."""
    result = HeartRateMeasurementParser(_DEVICE_ID).parse(data)
    assert result is None or isinstance(result, HeartRate)


# --- Property 1: round-trip of valid payloads ---------------------------------

_FLAG_VALUE_FORMAT_UINT16 = 0x01  # bit 0
_FLAG_SENSOR_CONTACT_DETECTED = 0x02  # bit 1
_FLAG_SENSOR_CONTACT_SUPPORTED = 0x04  # bit 2
_FLAG_ENERGY_EXPENDED_PRESENT = 0x08  # bit 3
_FLAG_RR_INTERVAL_PRESENT = 0x10  # bit 4

_UINT8_MAX = 0xFF
_UINT16_MAX = 0xFFFF


def _encode_hr_payload(
    *,
    value: int,
    value_is_uint16: bool,
    sensor_contact_supported: bool,
    sensor_contact_detected: bool,
    energy_expended: int | None,
    rr_intervals: list[int],
) -> tuple[bytes, bool | None]:
    """Build a valid Heart Rate Measurement payload with its expected sensor-contact state.

    Returns the encoded ``bytes`` and the tri-state ``sensor_contact`` the parser should
    decode: ``None`` when contact status is unsupported, otherwise the reported boolean.
    """
    flags = 0
    if value_is_uint16:
        flags |= _FLAG_VALUE_FORMAT_UINT16
    if sensor_contact_supported:
        flags |= _FLAG_SENSOR_CONTACT_SUPPORTED
        if sensor_contact_detected:
            flags |= _FLAG_SENSOR_CONTACT_DETECTED
    if energy_expended is not None:
        flags |= _FLAG_ENERGY_EXPENDED_PRESENT
    if rr_intervals:
        flags |= _FLAG_RR_INTERVAL_PRESENT

    payload = bytearray([flags])
    if value_is_uint16:
        payload += value.to_bytes(2, byteorder="little", signed=False)
    else:
        payload.append(value)
    if energy_expended is not None:
        payload += energy_expended.to_bytes(2, byteorder="little", signed=False)
    for rr in rr_intervals:
        payload += rr.to_bytes(2, byteorder="little", signed=False)

    expected_contact = sensor_contact_detected if sensor_contact_supported else None
    return bytes(payload), expected_contact


@st.composite
def _valid_hr_payloads(draw: st.DrawFn) -> tuple[bytes, int, bool | None]:
    """Strategy over valid payloads: both value formats, every sensor-contact configuration,
    and the optional energy-expended and RR-interval fields.

    Yields ``(payload, expected_value, expected_sensor_contact)``.
    """
    value_is_uint16 = draw(st.booleans())
    max_value = _UINT16_MAX if value_is_uint16 else _UINT8_MAX
    value = draw(st.integers(min_value=0, max_value=max_value))

    sensor_contact_supported = draw(st.booleans())
    sensor_contact_detected = draw(st.booleans())

    energy_expended = draw(st.one_of(st.none(), st.integers(min_value=0, max_value=_UINT16_MAX)))
    rr_intervals = draw(
        st.lists(st.integers(min_value=0, max_value=_UINT16_MAX), min_size=0, max_size=4)
    )

    payload, expected_contact = _encode_hr_payload(
        value=value,
        value_is_uint16=value_is_uint16,
        sensor_contact_supported=sensor_contact_supported,
        sensor_contact_detected=sensor_contact_detected,
        energy_expended=energy_expended,
        rr_intervals=rr_intervals,
    )
    return payload, value, expected_contact


# Feature: hr-pipeline, Property 1: Parser round-trips valid payloads
# Validates: Requirements FR-3a.1, FR-3a.2, FR-3a.3
@settings(max_examples=200)
@given(case=_valid_hr_payloads())
def test_parser_round_trips_valid_payloads(case: tuple[bytes, int, bool | None]) -> None:
    """Parsing a valid payload yields a HeartRate whose ``value`` equals the encoded value
    and whose ``sensor_contact`` equals the encoded tri-state (True/False/None), across both
    value formats and with optional energy-expended / RR-interval fields present."""
    payload, expected_value, expected_contact = case
    result = HeartRateMeasurementParser(_DEVICE_ID).parse(payload)
    assert isinstance(result, HeartRate)
    assert result.value == float(expected_value)
    assert result.sensor_contact is expected_contact
