# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the Temperature Measurement parser (GATT 0x2A1C).

Covers the Fahrenheit→Celsius normalization contract of
:class:`~vitals_on_fhir.adapters.temp_parser.TemperatureMeasurementParser`: a
Fahrenheit-flagged payload encoding ``C x 9/5 + 32`` and a Celsius-flagged
payload encoding ``C`` must parse to the same Celsius ``value`` (both ``~= C``).

Requirements: FR-TEMP-3, NFR-TEMP-6.
"""

from __future__ import annotations

import math
from datetime import datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from vitals_on_fhir.adapters.temp_parser import TemperatureMeasurementParser
from vitals_on_fhir.vitals.builtin.body_temperature import BodyTemperature

_DEVICE_ID = "test-thermometer"

# Temperature Measurement flags byte (offset 0) bit positions.
_FLAG_UNIT_FAHRENHEIT = 0x01  # bit 0: 0 -> Celsius, 1 -> Fahrenheit

_FLOAT_SIZE = 4


def _encode_float(mantissa: int, exponent: int = 0) -> bytes:
    """Encode a 32-bit IEEE-11073 FLOAT (8-bit exponent, 24-bit mantissa), little-endian."""
    raw = ((exponent & 0xFF) << 24) | (mantissa & 0x00FFFFFF)
    return raw.to_bytes(_FLOAT_SIZE, byteorder="little", signed=False)


def _temp_payload(*, mantissa: int, exponent: int, fahrenheit: bool) -> bytes:
    """Build a Temperature Measurement payload: flags byte + a temperature FLOAT.

    Only the unit flag is exercised here (no timestamp, no temperature-type),
    so ``value`` is compared directly against the encoded temperature.
    """
    flags = _FLAG_UNIT_FAHRENHEIT if fahrenheit else 0x00
    return bytes([flags]) + _encode_float(mantissa, exponent)


# Feature: body-temperature, Property 4: Fahrenheit normalization correctness
@given(
    # Encode temperatures as (mantissa x 10^-1) Celsius so both C and F have a
    # clean two-decimal FLOAT representation; keep the range physically sane so
    # the derived Fahrenheit mantissa also fits the 24-bit signed field.
    celsius_tenths=st.integers(min_value=0, max_value=1000),
)
@settings(max_examples=200)
def test_fahrenheit_normalization_correctness(celsius_tenths: int) -> None:
    """A Fahrenheit-flagged and a Celsius-flagged payload for the same temperature agree.

    For a Celsius value ``C``, the Celsius-flagged payload encodes ``C`` and the
    Fahrenheit-flagged payload encodes ``C x 9/5 + 32``. Both must parse to a
    ``value`` equal within tolerance (both ``~= C``), demonstrating that the
    parser normalizes Fahrenheit back to Celsius.
    """
    celsius = celsius_tenths / 10.0
    parser = TemperatureMeasurementParser(_DEVICE_ID)

    # Celsius payload: mantissa = celsius_tenths, exponent = -1 -> value = C.
    celsius_result = parser.parse(
        _temp_payload(mantissa=celsius_tenths, exponent=-1, fahrenheit=False)
    )

    # Fahrenheit payload: F = C * 9/5 + 32, encoded in hundredths (exponent -2)
    # so the exact fractional Fahrenheit value round-trips through the FLOAT.
    fahrenheit_hundredths = round((celsius * 9 / 5 + 32) * 100)
    fahrenheit_result = parser.parse(
        _temp_payload(mantissa=fahrenheit_hundredths, exponent=-2, fahrenheit=True)
    )

    assert isinstance(celsius_result, BodyTemperature)
    assert isinstance(fahrenheit_result, BodyTemperature)
    # Both readings represent the same Celsius temperature.
    assert math.isclose(celsius_result.value, celsius, rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(fahrenheit_result.value, celsius, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(
        celsius_result.value, fahrenheit_result.value, rel_tol=1e-9, abs_tol=1e-9
    )


# --- Property 2: parser never crashes on arbitrary bytes ----------------------

# Additional flags byte bits used by the robustness edge cases below.
_FLAG_TIMESTAMP_PRESENT = 0x02  # bit 1: date-time field present (7 bytes)
_FLAG_TEMPERATURE_TYPE_PRESENT = 0x04  # bit 2: temperature-type field present (1 byte)


# Feature: body-temperature, Property 2: Parser never crashes on arbitrary bytes
# Validates: Requirements FR-TEMP-3, NFR-TEMP-6
@settings(max_examples=200)
@given(data=st.binary())
def test_parser_never_crashes_on_arbitrary_bytes(data: bytes) -> None:
    """The parser tolerates any byte string: it returns ``None`` or a valid
    ``BodyTemperature`` and never raises for arbitrary input (empty, single-byte,
    and very long payloads included)."""
    result = TemperatureMeasurementParser(_DEVICE_ID).parse(data)
    assert result is None or isinstance(result, BodyTemperature)


# --- Edge-case examples: all must be dropped (None) ---------------------------


def test_truncated_payload_returns_none() -> None:
    """A payload too short for the mandatory temperature FLOAT is dropped (None)."""
    # Flags declare a plain Celsius reading (needs 1 + 4 bytes) but only 3 bytes follow.
    payload = bytes([0x00]) + bytes(_FLOAT_SIZE - 1)
    assert TemperatureMeasurementParser(_DEVICE_ID).parse(payload) is None


def test_reserved_float_payload_returns_none() -> None:
    """A reserved/unusable temperature FLOAT (NaN mantissa) drops the reading (None)."""
    payload = bytes([0x00]) + _encode_float(0x007FFFFF)  # NaN
    assert TemperatureMeasurementParser(_DEVICE_ID).parse(payload) is None


def test_invalid_calendar_date_timestamp_returns_none() -> None:
    """A declared timestamp with an invalid calendar date (all-zero) drops the reading (None)."""
    payload = bytes([_FLAG_TIMESTAMP_PRESENT]) + _encode_float(3700, -2) + bytes(7)
    assert TemperatureMeasurementParser(_DEVICE_ID).parse(payload) is None


def test_short_with_temperature_type_present_returns_none() -> None:
    """Flags declaring a temperature-type field, but a payload missing it, is dropped (None)."""
    # Flags declare the 1-byte temperature-type field (needs 1 + 4 + 1 bytes) but the
    # temperature-type byte is absent, so the payload is one byte short.
    payload = bytes([_FLAG_TEMPERATURE_TYPE_PRESENT]) + _encode_float(3700, -2)
    assert TemperatureMeasurementParser(_DEVICE_ID).parse(payload) is None


# --- Task 4.1: pure-function unit tests (parse_temp_flags / required_length /
# fahrenheit_to_celsius). Kept in clearly-named functions to coexist with the
# parser-contract and property tests written by parallel sub-tasks.
# Requirements: FR-TEMP-3, NFR-TEMP-6.

from vitals_on_fhir.adapters.datetime_field import TIMESTAMP_SIZE  # noqa: E402
from vitals_on_fhir.adapters.sfloat import FLOAT_SIZE  # noqa: E402
from vitals_on_fhir.adapters.temp_parser import (  # noqa: E402
    fahrenheit_to_celsius,
    parse_temp_flags,
    required_length,
)

# Temperature Measurement flags byte bit positions (task 4.1 tests).
_T41_FLAG_UNIT_FAHRENHEIT = 0x01  # bit 0: 0 -> Celsius, 1 -> Fahrenheit
_T41_FLAG_TIMESTAMP_PRESENT = 0x02  # bit 1: date-time field present
_T41_FLAG_TEMPERATURE_TYPE_PRESENT = 0x04  # bit 2: temperature-type field present

_T41_TEMPERATURE_TYPE_SIZE = 1  # bytes, length-accounted only


# --- parse_temp_flags: bit decode --------------------------------------------


def test_parse_temp_flags_all_clear() -> None:
    """A zero flags byte decodes to Celsius with no optional fields."""
    flags = parse_temp_flags(0x00)
    assert flags.unit_is_fahrenheit is False
    assert flags.timestamp_present is False
    assert flags.temperature_type_present is False


def test_parse_temp_flags_fahrenheit_bit() -> None:
    """Bit 0 selects the Fahrenheit unit without affecting the other bits."""
    flags = parse_temp_flags(_T41_FLAG_UNIT_FAHRENHEIT)
    assert flags.unit_is_fahrenheit is True
    assert flags.timestamp_present is False
    assert flags.temperature_type_present is False


def test_parse_temp_flags_timestamp_bit() -> None:
    """Bit 1 marks a timestamp present without affecting the other bits."""
    flags = parse_temp_flags(_T41_FLAG_TIMESTAMP_PRESENT)
    assert flags.unit_is_fahrenheit is False
    assert flags.timestamp_present is True
    assert flags.temperature_type_present is False


def test_parse_temp_flags_temperature_type_bit() -> None:
    """Bit 2 marks a temperature type present without affecting the other bits."""
    flags = parse_temp_flags(_T41_FLAG_TEMPERATURE_TYPE_PRESENT)
    assert flags.unit_is_fahrenheit is False
    assert flags.timestamp_present is False
    assert flags.temperature_type_present is True


def test_parse_temp_flags_all_set() -> None:
    """All three relevant bits set decode to all fields present."""
    byte = (
        _T41_FLAG_UNIT_FAHRENHEIT
        | _T41_FLAG_TIMESTAMP_PRESENT
        | _T41_FLAG_TEMPERATURE_TYPE_PRESENT
    )
    flags = parse_temp_flags(byte)
    assert flags.unit_is_fahrenheit is True
    assert flags.timestamp_present is True
    assert flags.temperature_type_present is True


def test_parse_temp_flags_ignores_unrelated_bits() -> None:
    """Bits above bit 2 are reserved and do not affect the decoded fields."""
    flags = parse_temp_flags(0xF8)  # bits 3..7 set, bits 0..2 clear
    assert flags.unit_is_fahrenheit is False
    assert flags.timestamp_present is False
    assert flags.temperature_type_present is False


# --- required_length: every optional-field combination -----------------------


def test_required_length_base() -> None:
    """With no optional fields, length is the flags byte plus the FLOAT."""
    flags = parse_temp_flags(0x00)
    assert required_length(flags) == 1 + FLOAT_SIZE


def test_required_length_with_timestamp() -> None:
    """A declared timestamp adds the 7-byte date-time field."""
    flags = parse_temp_flags(_T41_FLAG_TIMESTAMP_PRESENT)
    assert required_length(flags) == 1 + FLOAT_SIZE + TIMESTAMP_SIZE


def test_required_length_with_temperature_type() -> None:
    """A declared temperature type adds its 1-byte field (length-accounted only)."""
    flags = parse_temp_flags(_T41_FLAG_TEMPERATURE_TYPE_PRESENT)
    assert required_length(flags) == 1 + FLOAT_SIZE + _T41_TEMPERATURE_TYPE_SIZE


def test_required_length_with_timestamp_and_temperature_type() -> None:
    """Both optional fields present add both their sizes."""
    flags = parse_temp_flags(
        _T41_FLAG_TIMESTAMP_PRESENT | _T41_FLAG_TEMPERATURE_TYPE_PRESENT
    )
    assert (
        required_length(flags)
        == 1 + FLOAT_SIZE + TIMESTAMP_SIZE + _T41_TEMPERATURE_TYPE_SIZE
    )


def test_required_length_unaffected_by_unit_flag() -> None:
    """The Fahrenheit unit flag carries no payload, so it does not change length."""
    celsius = parse_temp_flags(0x00)
    fahrenheit = parse_temp_flags(_T41_FLAG_UNIT_FAHRENHEIT)
    assert required_length(fahrenheit) == required_length(celsius)


# --- fahrenheit_to_celsius: known pairs --------------------------------------


def test_fahrenheit_to_celsius_body_temperature() -> None:
    """98.6 degrees F is body temperature: 37.0 degrees C."""
    assert fahrenheit_to_celsius(98.6) == 37.0


def test_fahrenheit_to_celsius_freezing_point() -> None:
    """32 degrees F is the freezing point of water: 0.0 degrees C."""
    assert fahrenheit_to_celsius(32.0) == 0.0


def test_fahrenheit_to_celsius_boiling_point() -> None:
    """212 degrees F is the boiling point of water: 100.0 degrees C."""
    assert fahrenheit_to_celsius(212.0) == 100.0


def test_fahrenheit_to_celsius_scale_intersection() -> None:
    """The Fahrenheit and Celsius scales coincide at -40 degrees."""
    assert fahrenheit_to_celsius(-40.0) == -40.0


# --- Property 3 ---------------------------------------------------------------
# Well-formed payload build -> parse round-trip (design §3, Property 3).
# Helpers and constants below are uniquely prefixed (``_temp3_`` / ``_TEMP3_``)
# so this block coexists with the Property 4 test above in the same file.

_TEMP3_DEVICE_ID = "test-thermometer-rt"

# Temperature Measurement flags byte bit positions.
_TEMP3_FLAG_UNIT_FAHRENHEIT = 0x01
_TEMP3_FLAG_TIMESTAMP_PRESENT = 0x02
_TEMP3_FLAG_TEMPERATURE_TYPE_PRESENT = 0x04

# A pinned clock for the timestamp-absent branch.
_TEMP3_PINNED_NOW = datetime(2021, 3, 14, 9, 26, 53).astimezone()


def _temp3_encode_float(mantissa: int, exponent: int) -> bytes:
    """Encode a 32-bit IEEE-11073 FLOAT (8-bit exponent, 24-bit mantissa), little-endian."""
    raw = ((exponent & 0xFF) << 24) | (mantissa & 0x00FFFFFF)
    return raw.to_bytes(4, byteorder="little", signed=False)


def _temp3_build_payload(
    *,
    celsius_hundredths: int,
    timestamp: tuple[int, int, int, int, int, int] | None = None,
    temperature_type_present: bool = False,
) -> bytes:
    """Build a valid Celsius Temperature Measurement payload.

    The temperature is a 32-bit FLOAT with mantissa ``celsius_hundredths`` and
    exponent ``-2`` (i.e. ``celsius_hundredths x 10^-2`` Celsius). The optional
    7-byte org.bluetooth date-time is appended when ``timestamp`` is given, and
    a length-only temperature-type byte when ``temperature_type_present``.
    """
    flags = 0
    if timestamp is not None:
        flags |= _TEMP3_FLAG_TIMESTAMP_PRESENT
    if temperature_type_present:
        flags |= _TEMP3_FLAG_TEMPERATURE_TYPE_PRESENT

    payload = bytearray([flags])
    payload += _temp3_encode_float(celsius_hundredths, -2)
    if timestamp is not None:
        year, month, day, hour, minute, second = timestamp
        payload += year.to_bytes(2, byteorder="little", signed=False)
        payload += bytes([month, day, hour, minute, second])
    if temperature_type_present:
        payload += bytes([0x01])  # temperature-type field: length-accounted only
    return bytes(payload)


# Feature: body-temperature, Property 3: Well-formed payload build → parse round-trip
@settings(max_examples=200)
@given(
    # Celsius in [10.00, 47.00] as integer hundredths, kept in-range so the
    # source value round-trips cleanly through the FLOAT.
    celsius_hundredths=st.integers(min_value=1000, max_value=4700),
    timestamp_present=st.booleans(),
    temperature_type_present=st.booleans(),
    year=st.integers(min_value=2000, max_value=2099),
    month=st.integers(min_value=1, max_value=12),
    day=st.integers(min_value=1, max_value=28),
    hour=st.integers(min_value=0, max_value=23),
    minute=st.integers(min_value=0, max_value=59),
    second=st.integers(min_value=0, max_value=59),
)
def test_well_formed_payload_round_trips(
    celsius_hundredths: int,
    timestamp_present: bool,
    temperature_type_present: bool,
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int,
) -> None:
    """A built Celsius payload parses back to a matching ``BodyTemperature``.

    ``value`` equals the source Celsius temperature within tolerance for every
    optional-field flag combination. When the timestamp flag is set, ``effective``
    equals the encoded date-time as host-local, tz-aware time; when it is absent,
    ``effective`` comes from the pinned injected clock.
    """
    expected_celsius = celsius_hundredths / 100.0
    timestamp = (year, month, day, hour, minute, second) if timestamp_present else None

    payload = _temp3_build_payload(
        celsius_hundredths=celsius_hundredths,
        timestamp=timestamp,
        temperature_type_present=temperature_type_present,
    )
    parser = TemperatureMeasurementParser(_TEMP3_DEVICE_ID, now=lambda: _TEMP3_PINNED_NOW)
    result = parser.parse(payload)

    assert isinstance(result, BodyTemperature)
    assert result.device_id == _TEMP3_DEVICE_ID
    assert math.isclose(result.value, expected_celsius, rel_tol=1e-9, abs_tol=1e-9)
    assert result.effective.tzinfo is not None

    if timestamp_present:
        expected_effective = datetime(year, month, day, hour, minute, second).astimezone()
        assert result.effective == expected_effective
    else:
        assert result.effective == _TEMP3_PINNED_NOW
