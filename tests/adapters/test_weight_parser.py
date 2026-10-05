# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the Weight Measurement parser (GATT 0x2A9D).

Covers the pure functions (``parse_weight_flags``, ``required_length``,
``scale_weight``) and the parser class contract of
:class:`~vitals_on_fhir.adapters.weight_parser.WeightMeasurementParser`,
including the unit-dependent uint16 scaling (SI 0.005 kg vs Imperial 0.01 lb→kg),
the pounds→kilograms normalization, optional-field length accounting, and the
robustness/round-trip properties.

Requirements: FR-WT-2, FR-WT-3, NFR-WT-6.
"""

from __future__ import annotations

import math
from datetime import datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from vitals_on_fhir.adapters.datetime_field import TIMESTAMP_SIZE
from vitals_on_fhir.adapters.weight_parser import (
    WeightMeasurementParser,
    parse_weight_flags,
    required_length,
    scale_weight,
)
from vitals_on_fhir.vitals.builtin.body_weight import BodyWeight

_DEVICE_ID = "test-weight-scale"

# Weight Measurement flags byte (offset 0) bit positions.
_FLAG_UNIT_IMPERIAL = 0x01  # bit 0: 0 -> SI (kg), 1 -> Imperial (lb)
_FLAG_TIMESTAMP_PRESENT = 0x02  # bit 1: date-time field present (7 bytes)
_FLAG_USER_ID_PRESENT = 0x04  # bit 2: user-ID field present (1 byte)
_FLAG_BMI_HEIGHT_PRESENT = 0x08  # bit 3: BMI + height fields present (4 bytes)

_WEIGHT_SIZE = 2
_USER_ID_SIZE = 1
_BMI_HEIGHT_SIZE = 4
_LB_TO_KG = 0.45359237


def _encode_uint16(value: int) -> bytes:
    """Encode a uint16 little-endian."""
    return (value & 0xFFFF).to_bytes(2, byteorder="little", signed=False)


def _weight_payload(
    *,
    raw: int,
    imperial: bool,
    timestamp: tuple[int, int, int, int, int, int] | None = None,
    user_id_present: bool = False,
    bmi_height_present: bool = False,
) -> bytes:
    """Build a Weight Measurement payload: flags byte + uint16 weight + optionals.

    The optional org.bluetooth 7-byte date-time is appended when ``timestamp`` is
    given; length-only user-ID and BMI/height fields are appended when their flags
    are set.
    """
    flags = _FLAG_UNIT_IMPERIAL if imperial else 0x00
    if timestamp is not None:
        flags |= _FLAG_TIMESTAMP_PRESENT
    if user_id_present:
        flags |= _FLAG_USER_ID_PRESENT
    if bmi_height_present:
        flags |= _FLAG_BMI_HEIGHT_PRESENT

    payload = bytearray([flags])
    payload += _encode_uint16(raw)
    if timestamp is not None:
        year, month, day, hour, minute, second = timestamp
        payload += year.to_bytes(2, byteorder="little", signed=False)
        payload += bytes([month, day, hour, minute, second])
    if user_id_present:
        payload += bytes([0x01])  # user-ID: length-accounted only, never decoded
    if bmi_height_present:
        payload += bytes(_BMI_HEIGHT_SIZE)  # BMI + height: length-accounted only
    return bytes(payload)


# --- Task 2.1: pure-function unit tests --------------------------------------


def test_parse_weight_flags_all_clear() -> None:
    """A zero flags byte decodes to SI units with no optional fields."""
    flags = parse_weight_flags(0x00)
    assert flags.unit_is_imperial is False
    assert flags.timestamp_present is False
    assert flags.user_id_present is False
    assert flags.bmi_height_present is False


def test_parse_weight_flags_imperial_bit() -> None:
    """Bit 0 selects Imperial units without affecting the other bits."""
    flags = parse_weight_flags(_FLAG_UNIT_IMPERIAL)
    assert flags.unit_is_imperial is True
    assert flags.timestamp_present is False
    assert flags.user_id_present is False
    assert flags.bmi_height_present is False


def test_parse_weight_flags_all_set() -> None:
    """All four relevant bits set decode to all fields present."""
    byte = (
        _FLAG_UNIT_IMPERIAL
        | _FLAG_TIMESTAMP_PRESENT
        | _FLAG_USER_ID_PRESENT
        | _FLAG_BMI_HEIGHT_PRESENT
    )
    flags = parse_weight_flags(byte)
    assert flags.unit_is_imperial is True
    assert flags.timestamp_present is True
    assert flags.user_id_present is True
    assert flags.bmi_height_present is True


def test_parse_weight_flags_ignores_unrelated_bits() -> None:
    """Bits above bit 3 are reserved and do not affect the decoded fields."""
    flags = parse_weight_flags(0xF0)  # bits 4..7 set, bits 0..3 clear
    assert flags.unit_is_imperial is False
    assert flags.timestamp_present is False
    assert flags.user_id_present is False
    assert flags.bmi_height_present is False


def test_required_length_base() -> None:
    """With no optional fields, length is the flags byte plus the uint16 weight."""
    flags = parse_weight_flags(0x00)
    assert required_length(flags) == 1 + _WEIGHT_SIZE


def test_required_length_with_timestamp() -> None:
    """A declared timestamp adds the 7-byte date-time field."""
    flags = parse_weight_flags(_FLAG_TIMESTAMP_PRESENT)
    assert required_length(flags) == 1 + _WEIGHT_SIZE + TIMESTAMP_SIZE


def test_required_length_with_user_id() -> None:
    """A declared user ID adds its 1-byte field (length-accounted only)."""
    flags = parse_weight_flags(_FLAG_USER_ID_PRESENT)
    assert required_length(flags) == 1 + _WEIGHT_SIZE + _USER_ID_SIZE


def test_required_length_with_bmi_height() -> None:
    """A declared BMI + height pair adds its 4-byte field (length-accounted only)."""
    flags = parse_weight_flags(_FLAG_BMI_HEIGHT_PRESENT)
    assert required_length(flags) == 1 + _WEIGHT_SIZE + _BMI_HEIGHT_SIZE


def test_required_length_all_optional_fields() -> None:
    """All optional fields present add all their sizes."""
    flags = parse_weight_flags(
        _FLAG_TIMESTAMP_PRESENT | _FLAG_USER_ID_PRESENT | _FLAG_BMI_HEIGHT_PRESENT
    )
    assert (
        required_length(flags)
        == 1 + _WEIGHT_SIZE + TIMESTAMP_SIZE + _USER_ID_SIZE + _BMI_HEIGHT_SIZE
    )


def test_required_length_unaffected_by_unit_flag() -> None:
    """The Imperial unit flag carries no payload, so it does not change length."""
    si = parse_weight_flags(0x00)
    imperial = parse_weight_flags(_FLAG_UNIT_IMPERIAL)
    assert required_length(imperial) == required_length(si)


def test_scale_weight_si_known_pair() -> None:
    """In SI mode a raw 14000 is 70.0 kg (0.005 kg per unit)."""
    assert scale_weight(14000, imperial=False) == 70.0


def test_scale_weight_imperial_known_pair() -> None:
    """In Imperial mode a raw value scales by 0.01 lb then converts to kilograms."""
    # raw 15432 -> 154.32 lb -> 154.32 * 0.45359237 kg.
    expected = 15432 * 0.01 * _LB_TO_KG
    assert math.isclose(scale_weight(15432, imperial=True), expected, rel_tol=1e-12)


def test_scale_weight_multipliers_not_interchanged() -> None:
    """SI and Imperial scaling of the same raw value differ (not interchangeable)."""
    raw = 14000
    assert scale_weight(raw, imperial=False) != scale_weight(raw, imperial=True)


# --- Task 2.2: Property 1 — unit-scaling correctness -------------------------


# Feature: weight-body-mass, Property 1: Unit-scaling correctness
@settings(max_examples=200)
@given(raw=st.integers(min_value=0, max_value=0xFFFF))
def test_unit_scaling_correctness(raw: int) -> None:
    """``scale_weight`` applies the correct per-unit resolution and always yields kg.

    SI mode is ``raw x 0.005`` kg; Imperial mode is ``raw x 0.01 lb`` then
    converted to kilograms. For any non-zero raw value the two results differ,
    confirming the multipliers are not interchangeable.
    """
    si = scale_weight(raw, imperial=False)
    imperial = scale_weight(raw, imperial=True)
    assert math.isclose(si, raw * 0.005, rel_tol=1e-12, abs_tol=1e-12)
    assert math.isclose(imperial, raw * 0.01 * _LB_TO_KG, rel_tol=1e-12, abs_tol=1e-12)
    if raw != 0:
        assert si != imperial


# --- Task 2.3: Property 2 — parser never crashes on arbitrary bytes ----------


# Feature: weight-body-mass, Property 2: Parser never crashes on arbitrary bytes
# Validates: Requirements FR-WT-3, NFR-WT-6
@settings(max_examples=200)
@given(data=st.binary())
def test_parser_never_crashes_on_arbitrary_bytes(data: bytes) -> None:
    """The parser tolerates any byte string: it returns ``None`` or a valid
    ``BodyWeight`` and never raises for arbitrary input (empty, single-byte, and
    very long payloads included)."""
    result = WeightMeasurementParser(_DEVICE_ID).parse(data)
    assert result is None or isinstance(result, BodyWeight)


# --- Edge-case examples: all must be dropped (None) --------------------------


def test_truncated_payload_returns_none() -> None:
    """A payload too short for the mandatory uint16 weight is dropped (None)."""
    payload = bytes([0x00]) + bytes(_WEIGHT_SIZE - 1)  # only 1 weight byte
    assert WeightMeasurementParser(_DEVICE_ID).parse(payload) is None


def test_empty_payload_returns_none() -> None:
    """An empty payload is dropped (None)."""
    assert WeightMeasurementParser(_DEVICE_ID).parse(b"") is None


def test_invalid_calendar_date_timestamp_returns_none() -> None:
    """A declared timestamp with an invalid calendar date (all-zero) drops the reading (None)."""
    payload = bytes([_FLAG_TIMESTAMP_PRESENT]) + _encode_uint16(14000) + bytes(TIMESTAMP_SIZE)
    assert WeightMeasurementParser(_DEVICE_ID).parse(payload) is None


def test_short_with_user_id_present_returns_none() -> None:
    """Flags declaring a user-ID field, but a payload missing it, is dropped (None)."""
    payload = bytes([_FLAG_USER_ID_PRESENT]) + _encode_uint16(14000)
    assert WeightMeasurementParser(_DEVICE_ID).parse(payload) is None


def test_short_with_bmi_height_present_returns_none() -> None:
    """Flags declaring a BMI + height pair, but a payload missing it, is dropped (None)."""
    payload = bytes([_FLAG_BMI_HEIGHT_PRESENT]) + _encode_uint16(14000)
    assert WeightMeasurementParser(_DEVICE_ID).parse(payload) is None


# --- Task 2.4: Property 3 — well-formed build → parse round-trip -------------

_PINNED_NOW = datetime(2021, 3, 14, 9, 26, 53).astimezone()


# Feature: weight-body-mass, Property 3: Well-formed payload build → parse round-trip
@settings(max_examples=200)
@given(
    # SI raw uint16 in [400, 60000] -> [2.0, 300.0] kg at 0.005 kg/unit.
    raw=st.integers(min_value=400, max_value=60000),
    timestamp_present=st.booleans(),
    user_id_present=st.booleans(),
    bmi_height_present=st.booleans(),
    year=st.integers(min_value=2000, max_value=2099),
    month=st.integers(min_value=1, max_value=12),
    day=st.integers(min_value=1, max_value=28),
    hour=st.integers(min_value=0, max_value=23),
    minute=st.integers(min_value=0, max_value=59),
    second=st.integers(min_value=0, max_value=59),
)
def test_well_formed_payload_round_trips(
    raw: int,
    timestamp_present: bool,
    user_id_present: bool,
    bmi_height_present: bool,
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int,
) -> None:
    """A built SI payload parses back to a matching ``BodyWeight``.

    ``value`` equals the source kilogram weight within tolerance for every
    optional-field flag combination. When the timestamp flag is set, ``effective``
    equals the encoded date-time as host-local, tz-aware time; when it is absent,
    ``effective`` comes from the pinned injected clock.
    """
    expected_kg = raw * 0.005
    timestamp = (year, month, day, hour, minute, second) if timestamp_present else None

    payload = _weight_payload(
        raw=raw,
        imperial=False,
        timestamp=timestamp,
        user_id_present=user_id_present,
        bmi_height_present=bmi_height_present,
    )
    parser = WeightMeasurementParser(_DEVICE_ID, now=lambda: _PINNED_NOW)
    result = parser.parse(payload)

    assert isinstance(result, BodyWeight)
    assert result.device_id == _DEVICE_ID
    assert math.isclose(result.value, expected_kg, rel_tol=1e-9, abs_tol=1e-9)
    assert result.effective.tzinfo is not None

    if timestamp_present:
        expected_effective = datetime(year, month, day, hour, minute, second).astimezone()
        assert result.effective == expected_effective
    else:
        assert result.effective == _PINNED_NOW


# --- Task 2.5: Property 4 — Imperial normalization correctness ---------------


# Feature: weight-body-mass, Property 4: Imperial normalization correctness
@settings(max_examples=200)
@given(
    # A source SI raw value; the Imperial raw encoding the same physical weight
    # is derived below so both payloads parse to the same kilograms. Capped so the
    # derived Imperial raw (0.01-lb units) stays within a uint16: 59000 x 0.005 kg
    # ~= 295 kg -> ~65058 lb-units, just under 65535.
    si_raw=st.integers(min_value=400, max_value=59000),
)
def test_imperial_normalization_correctness(si_raw: int) -> None:
    """A Fahrenheit-analogue: SI and Imperial payloads for the same weight agree.

    For a physical weight of ``si_raw x 0.005`` kg, the Imperial-flagged payload
    encodes the equivalent raw pounds (``kg / 0.45359237 / 0.01``). Both payloads
    must parse to a ``value`` equal within tolerance (both ``~= C`` kilograms),
    demonstrating the parser normalizes pounds back to kilograms.
    """
    kilograms = si_raw * 0.005
    parser = WeightMeasurementParser(_DEVICE_ID)

    si_result = parser.parse(_weight_payload(raw=si_raw, imperial=False))

    # Imperial raw encodes the same physical weight in 0.01-lb units.
    imperial_raw = round(kilograms / _LB_TO_KG / 0.01)
    imperial_result = parser.parse(_weight_payload(raw=imperial_raw, imperial=True))

    assert isinstance(si_result, BodyWeight)
    assert isinstance(imperial_result, BodyWeight)
    assert math.isclose(si_result.value, kilograms, rel_tol=1e-9, abs_tol=1e-9)
    # Imperial round-trips through integer 0.01-lb units, so allow a small tolerance.
    assert math.isclose(imperial_result.value, kilograms, rel_tol=0.0, abs_tol=0.005)


# --- Task 3.1: parser timezone threading + no-timestamp-unchanged ------------


def test_parser_tz_interprets_device_timestamp_in_zone() -> None:
    """A parser built with ``tz=ZoneInfo("UTC")`` yields a UTC-aware ``effective``.

    A timestamp-present payload's zoneless device wall-clock is interpreted as
    being in the configured zone: the calendar fields are unchanged and the
    result carries the UTC offset (design Testing Strategy 8/10; one parser
    exercises the shared helper for all three timestamp-decoding parsers).
    """
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    timestamp = (2021, 3, 14, 9, 26, 53)
    payload = _weight_payload(raw=14000, imperial=False, timestamp=timestamp)

    parser = WeightMeasurementParser(_DEVICE_ID, tz=ZoneInfo("UTC"))
    result = parser.parse(payload)

    assert isinstance(result, BodyWeight)
    assert result.effective == datetime(2021, 3, 14, 9, 26, 53, tzinfo=ZoneInfo("UTC"))
    # Interpreted as being in the zone (offset attached), not shifted.
    assert result.effective.utcoffset() == timedelta(0)


def test_parser_tz_does_not_change_no_timestamp_path() -> None:
    """A timestamp-absent payload uses the host-local ``now()`` fallback regardless of ``tz``.

    The ``timezone`` setting is consumed only at the device-timestamp decode call
    site; a reading that carries no device timestamp keeps its processing-time
    ``effective`` from the injected clock, unaffected by ``tz`` (FR-CFG-4;
    design Testing Strategy 10).
    """
    from zoneinfo import ZoneInfo

    payload = _weight_payload(raw=14000, imperial=False, timestamp=None)

    parser = WeightMeasurementParser(_DEVICE_ID, now=lambda: _PINNED_NOW, tz=ZoneInfo("UTC"))
    result = parser.parse(payload)

    assert isinstance(result, BodyWeight)
    assert result.effective == _PINNED_NOW
