# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the Blood Pressure Measurement parser (GATT 0x2A35).

Covers SFLOAT decoding (including reserved/unusable values), the flags byte,
required-length accounting, kPa→mmHg normalization, local-time timestamp
decoding, and the ``parse`` contract for well-formed and malformed payloads.

Requirements: FR-HH-5, FR-HH-6.
"""

from __future__ import annotations

from datetime import datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from vitals_on_fhir.adapters.bp_parser import (
    BloodPressureMeasurementParser,
    decode_sfloat,
    decode_timestamp,
    kpa_to_mmhg,
    parse_bp_flags,
    required_length,
)
from vitals_on_fhir.vitals.builtin.blood_pressure import BloodPressure

_DEVICE_ID = "test-cuff"

# Flags byte bits.
_FLAG_UNIT_KPA = 0x01
_FLAG_TIMESTAMP_PRESENT = 0x02
_FLAG_PULSE_RATE_PRESENT = 0x04


def _parser() -> BloodPressureMeasurementParser:
    """Build a parser bound to a fixed device id for deterministic tests."""
    return BloodPressureMeasurementParser(_DEVICE_ID)


def _encode_sfloat(mantissa: int, exponent: int = 0) -> bytes:
    """Encode a 16-bit IEEE-11073 SFLOAT (4-bit exponent, 12-bit mantissa), little-endian."""
    raw = ((exponent & 0x0F) << 12) | (mantissa & 0x0FFF)
    return raw.to_bytes(2, byteorder="little", signed=False)


def _bp_payload(
    *,
    systolic: int,
    diastolic: int,
    map_value: int = 90,
    unit_kpa: bool = False,
    timestamp: tuple[int, int, int, int, int, int] | None = None,
) -> bytes:
    """Build a valid Blood Pressure Measurement payload (integer SFLOAT mantissas, exp 0)."""
    flags = 0
    if unit_kpa:
        flags |= _FLAG_UNIT_KPA
    if timestamp is not None:
        flags |= _FLAG_TIMESTAMP_PRESENT

    payload = bytearray([flags])
    payload += _encode_sfloat(systolic)
    payload += _encode_sfloat(diastolic)
    payload += _encode_sfloat(map_value)
    if timestamp is not None:
        year, month, day, hour, minute, second = timestamp
        payload += year.to_bytes(2, byteorder="little", signed=False)
        payload += bytes([month, day, hour, minute, second])
    return bytes(payload)


# --- Pure-function tests ------------------------------------------------------


def test_parse_bp_flags_decodes_bits() -> None:
    """Each relevant flag bit maps to the corresponding ``BpFlags`` field."""
    flags = parse_bp_flags(_FLAG_UNIT_KPA | _FLAG_TIMESTAMP_PRESENT)
    assert flags.unit_is_kpa is True
    assert flags.timestamp_present is True
    assert flags.pulse_rate_present is False


def test_required_length_accounts_for_optional_fields() -> None:
    """Required length grows with each optional field the flags declare."""
    base = parse_bp_flags(0x00)
    assert required_length(base) == 1 + 6  # flags + 3 SFLOATs

    with_ts = parse_bp_flags(_FLAG_TIMESTAMP_PRESENT)
    assert required_length(with_ts) == 1 + 6 + 7

    with_ts_pulse = parse_bp_flags(_FLAG_TIMESTAMP_PRESENT | _FLAG_PULSE_RATE_PRESENT)
    assert required_length(with_ts_pulse) == 1 + 6 + 7 + 2


def test_decode_sfloat_integer_value() -> None:
    """A mantissa with exponent 0 decodes to that integer value."""
    assert decode_sfloat(_encode_sfloat(120, 0), 0) == 120.0


def test_decode_sfloat_negative_exponent() -> None:
    """A negative exponent scales the mantissa by a power of ten."""
    # 985 x 10^-1 = 98.5
    assert decode_sfloat(_encode_sfloat(985, -1), 0) == 98.5


def test_decode_sfloat_reserved_values_return_none() -> None:
    """Reserved mantissas (NaN, NRes, ±INF, reserved) decode to ``None``."""
    for reserved in (0x07FF, 0x0800, 0x07FE, 0x0802, 0x0801):
        assert decode_sfloat(_encode_sfloat(reserved, 0), 0) is None


def test_kpa_to_mmhg() -> None:
    """kPa is converted to mmHg using the standard factor."""
    assert kpa_to_mmhg(1.0) == 7.50062


def test_decode_timestamp_is_local_aware() -> None:
    """The date-time field decodes to a tz-aware local datetime with the right fields."""
    payload = (2026).to_bytes(2, "little") + bytes([9, 23, 14, 5, 30])
    result = decode_timestamp(payload, 0)
    assert result is not None
    assert result.tzinfo is not None
    assert (result.year, result.month, result.day) == (2026, 9, 23)
    assert (result.hour, result.minute, result.second) == (14, 5, 30)


# --- parse() contract ---------------------------------------------------------


def test_parse_well_formed_mmhg() -> None:
    """A well-formed mmHg payload yields a ``BloodPressure`` with systolic/diastolic."""
    result = _parser().parse(_bp_payload(systolic=118, diastolic=76))
    assert isinstance(result, BloodPressure)
    assert result.systolic == 118.0
    assert result.diastolic == 76.0
    assert result.device_id == _DEVICE_ID
    assert result.effective.tzinfo is not None


def test_parse_normalizes_kpa_to_mmhg() -> None:
    """A kPa payload has systolic/diastolic normalized to mmHg."""
    result = _parser().parse(_bp_payload(systolic=16, diastolic=10, unit_kpa=True))
    assert isinstance(result, BloodPressure)
    assert result.systolic == kpa_to_mmhg(16.0)
    assert result.diastolic == kpa_to_mmhg(10.0)


def test_parse_uses_embedded_timestamp() -> None:
    """When the timestamp flag is set, ``effective`` comes from the payload (store-and-forward)."""
    ts = (2020, 1, 2, 3, 4, 5)
    result = _parser().parse(_bp_payload(systolic=120, diastolic=80, timestamp=ts))
    assert isinstance(result, BloodPressure)
    assert (result.effective.year, result.effective.month, result.effective.day) == (2020, 1, 2)
    assert result.effective.tzinfo is not None


def test_parse_uses_now_when_no_timestamp() -> None:
    """Without a timestamp flag, ``effective`` comes from the injected clock."""
    fixed = datetime(2019, 6, 15, 8, 0, 0).astimezone()
    parser = BloodPressureMeasurementParser(_DEVICE_ID, now=lambda: fixed)
    result = parser.parse(_bp_payload(systolic=120, diastolic=80))
    assert isinstance(result, BloodPressure)
    assert result.effective == fixed


def test_parse_short_payload_returns_none() -> None:
    """A payload too short for its declared fields is dropped (None)."""
    # Flags declare a timestamp, but only the three SFLOATs are present.
    payload = bytearray([_FLAG_TIMESTAMP_PRESENT])
    payload += _encode_sfloat(120) + _encode_sfloat(80) + _encode_sfloat(90)
    assert _parser().parse(bytes(payload)) is None


def test_parse_empty_returns_none() -> None:
    """A zero-length payload is dropped (None)."""
    assert _parser().parse(b"") is None


def test_parse_reserved_systolic_returns_none() -> None:
    """A reserved/unusable systolic SFLOAT drops the whole reading."""
    payload = bytearray([0x00])
    payload += _encode_sfloat(0x07FF)  # NaN systolic
    payload += _encode_sfloat(80) + _encode_sfloat(90)
    assert _parser().parse(bytes(payload)) is None


def test_parse_invalid_timestamp_returns_none() -> None:
    """A timestamp flag with an invalid calendar date (e.g. all-zero) drops the reading."""
    payload = bytearray([_FLAG_TIMESTAMP_PRESENT])
    payload += _encode_sfloat(120) + _encode_sfloat(80) + _encode_sfloat(90)
    payload += bytes(7)  # year 0, month 0, ... -> invalid
    assert _parser().parse(bytes(payload)) is None


# --- Property tests -----------------------------------------------------------


@settings(max_examples=200)
@given(data=st.binary())
def test_parser_never_crashes_on_arbitrary_bytes(data: bytes) -> None:
    """The parser tolerates any byte string: returns ``None`` or a ``BloodPressure``.

    It never raises for arbitrary input (empty, single-byte, long payloads included).
    """
    result = BloodPressureMeasurementParser(_DEVICE_ID).parse(data)
    assert result is None or isinstance(result, BloodPressure)


@settings(max_examples=200)
@given(
    systolic=st.integers(min_value=0, max_value=300),
    diastolic=st.integers(min_value=0, max_value=200),
)
def test_parser_round_trips_valid_mmhg_payloads(systolic: int, diastolic: int) -> None:
    """A valid mmHg payload round-trips to a ``BloodPressure`` with the encoded values."""
    payload = _bp_payload(systolic=systolic, diastolic=diastolic)
    result = BloodPressureMeasurementParser(_DEVICE_ID).parse(payload)
    assert isinstance(result, BloodPressure)
    assert result.systolic == float(systolic)
    assert result.diastolic == float(diastolic)
