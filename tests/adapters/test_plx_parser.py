# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the PLX Continuous Measurement parser (GATT 0x2A5F).

Covers the flags byte decode, required-length accounting across optional-field
combinations, and the ``parse`` contract for well-formed, optional-fields-present,
and malformed/short/reserved-SFLOAT payloads.

Requirements: FR-SPO2-3, FR-SPO2-2, NFR-SPO2-4, NFR-SPO2-5, NFR-SPO2-6.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from vitals_on_fhir.adapters.plx_parser import (
    PlxContinuousMeasurementParser,
    parse_plx_flags,
    required_length,
)
from vitals_on_fhir.vitals.builtin.oxygen_saturation import OxygenSaturation

_DEVICE_ID = "test-oximeter"

# Flags byte bits.
_FLAG_SPO2PR_FAST = 0x01
_FLAG_SPO2PR_SLOW = 0x02
_FLAG_MEASUREMENT_STATUS = 0x04
_FLAG_DEVICE_SENSOR_STATUS = 0x08
_FLAG_PULSE_AMPLITUDE_INDEX = 0x10


def _parser() -> PlxContinuousMeasurementParser:
    """Build a parser bound to a fixed device id for deterministic tests."""
    return PlxContinuousMeasurementParser(_DEVICE_ID)


def _encode_sfloat(mantissa: int, exponent: int = 0) -> bytes:
    """Encode a 16-bit IEEE-11073 SFLOAT (4-bit exponent, 12-bit mantissa), little-endian."""
    raw = ((exponent & 0x0F) << 12) | (mantissa & 0x0FFF)
    return raw.to_bytes(2, byteorder="little", signed=False)


def _plx_payload(
    *,
    spo2: int,
    pulse_rate: int = 60,
    flags: int = 0,
    trailing: bytes = b"",
) -> bytes:
    """Build a PLX Continuous Measurement payload (integer SFLOAT mantissas, exp 0).

    ``trailing`` supplies the bytes for whatever optional fields ``flags`` declares.
    """
    payload = bytearray([flags])
    payload += _encode_sfloat(spo2)
    payload += _encode_sfloat(pulse_rate)
    payload += trailing
    return bytes(payload)


# --- Pure-function tests ------------------------------------------------------


def test_parse_plx_flags_decodes_bits() -> None:
    """Each relevant flag bit maps to the corresponding ``PlxFlags`` field."""
    flags = parse_plx_flags(_FLAG_SPO2PR_FAST | _FLAG_DEVICE_SENSOR_STATUS)
    assert flags.spo2pr_fast_present is True
    assert flags.device_sensor_status_present is True
    assert flags.spo2pr_slow_present is False
    assert flags.measurement_status_present is False
    assert flags.pulse_amplitude_index_present is False


def test_parse_plx_flags_all_bits_set() -> None:
    """All five relevant bits decode to True when set."""
    flags = parse_plx_flags(0x1F)
    assert flags.spo2pr_fast_present is True
    assert flags.spo2pr_slow_present is True
    assert flags.measurement_status_present is True
    assert flags.device_sensor_status_present is True
    assert flags.pulse_amplitude_index_present is True


def test_required_length_mandatory_only() -> None:
    """With no optional fields, the required length is flags + two SFLOATs."""
    assert required_length(parse_plx_flags(0x00)) == 1 + 4


def test_required_length_accounts_for_optional_fields() -> None:
    """Required length grows with each optional field the flags declare."""
    with_fast = parse_plx_flags(_FLAG_SPO2PR_FAST)
    assert required_length(with_fast) == 1 + 4 + 4

    with_slow = parse_plx_flags(_FLAG_SPO2PR_SLOW)
    assert required_length(with_slow) == 1 + 4 + 4

    with_status = parse_plx_flags(_FLAG_MEASUREMENT_STATUS)
    assert required_length(with_status) == 1 + 4 + 2

    with_device = parse_plx_flags(_FLAG_DEVICE_SENSOR_STATUS)
    assert required_length(with_device) == 1 + 4 + 3

    with_pai = parse_plx_flags(_FLAG_PULSE_AMPLITUDE_INDEX)
    assert required_length(with_pai) == 1 + 4 + 2


def test_required_length_all_optional_fields() -> None:
    """With every optional field present the sizes sum together."""
    all_flags = parse_plx_flags(0x1F)
    # flags + mandatory pair(4) + fast(4) + slow(4) + status(2) + device(3) + pai(2)
    assert required_length(all_flags) == 1 + 4 + 4 + 4 + 2 + 3 + 2


# --- parse() contract ---------------------------------------------------------


def test_parse_well_formed_spo2() -> None:
    """A well-formed payload yields an ``OxygenSaturation`` with the SpO2 value."""
    result = _parser().parse(_plx_payload(spo2=98))
    assert isinstance(result, OxygenSaturation)
    assert result.value == 98.0
    assert result.device_id == _DEVICE_ID
    assert result.effective.tzinfo is not None


def test_parse_decodes_sfloat_exponent() -> None:
    """A negative exponent scales the SpO2 mantissa (e.g. 985 x 10^-1 = 98.5)."""
    payload = bytearray([0x00])
    payload += _encode_sfloat(985, -1)  # SpO2
    payload += _encode_sfloat(60)  # pulse rate
    result = _parser().parse(bytes(payload))
    assert isinstance(result, OxygenSaturation)
    assert result.value == 98.5


def test_parse_uses_injected_clock() -> None:
    """``effective`` comes from the injected clock (no timestamp in the payload)."""
    fixed = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
    parser = PlxContinuousMeasurementParser(_DEVICE_ID, now=lambda: fixed)
    result = parser.parse(_plx_payload(spo2=97))
    assert isinstance(result, OxygenSaturation)
    assert result.effective == fixed


def test_parse_default_clock_is_tz_aware() -> None:
    """The default clock produces a timezone-aware ``effective`` time."""
    result = _parser().parse(_plx_payload(spo2=95))
    assert isinstance(result, OxygenSaturation)
    assert result.effective.tzinfo is not None


def test_parse_with_optional_fields_present() -> None:
    """A payload declaring optional fields is decoded when long enough."""
    # Fast pair (4) + slow pair (4) + status (2) + device (3) + pai (2) = 15 trailing bytes.
    flags = 0x1F
    trailing = _encode_sfloat(97) + _encode_sfloat(61)  # fast pair
    trailing += _encode_sfloat(96) + _encode_sfloat(62)  # slow pair
    trailing += bytes([0x00, 0x00])  # measurement status
    trailing += bytes([0x00, 0x00, 0x00])  # device and sensor status
    trailing += _encode_sfloat(50)  # pulse amplitude index
    result = _parser().parse(_plx_payload(spo2=99, flags=flags, trailing=trailing))
    assert isinstance(result, OxygenSaturation)
    assert result.value == 99.0


def test_parse_short_payload_returns_none() -> None:
    """A payload too short for its declared fields is dropped (None)."""
    # Flags declare a fast SpO2-PR pair, but only the mandatory pair is present.
    payload = _plx_payload(spo2=98, flags=_FLAG_SPO2PR_FAST)
    assert _parser().parse(payload) is None


def test_parse_short_mandatory_returns_none() -> None:
    """A payload shorter than the mandatory part is dropped (None)."""
    payload = bytearray([0x00])
    payload += _encode_sfloat(98)  # SpO2 only; missing pulse-rate SFLOAT
    assert _parser().parse(bytes(payload)) is None


def test_parse_empty_returns_none() -> None:
    """A zero-length payload is dropped (None)."""
    assert _parser().parse(b"") is None


def test_parse_reserved_spo2_returns_none() -> None:
    """A reserved/unusable SpO2 SFLOAT drops the whole reading."""
    for reserved in (0x07FF, 0x0800, 0x07FE, 0x0802, 0x0801):
        payload = bytearray([0x00])
        payload += _encode_sfloat(reserved)  # reserved SpO2
        payload += _encode_sfloat(60)  # pulse rate
        assert _parser().parse(bytes(payload)) is None


# --- Property tests -----------------------------------------------------------


@settings(max_examples=200)
@given(data=st.binary())
def test_parser_never_crashes_on_arbitrary_bytes(data: bytes) -> None:
    """The parser tolerates any byte string: returns ``None`` or an ``OxygenSaturation``.

    It never raises for arbitrary input (empty, single-byte, long payloads included).
    """
    result = PlxContinuousMeasurementParser(_DEVICE_ID).parse(data)
    assert result is None or isinstance(result, OxygenSaturation)


@settings(max_examples=200)
@given(spo2=st.integers(min_value=0, max_value=100))
def test_parser_round_trips_valid_payloads(spo2: int) -> None:
    """A valid payload round-trips to an ``OxygenSaturation`` with the encoded value."""
    payload = _plx_payload(spo2=spo2)
    result = PlxContinuousMeasurementParser(_DEVICE_ID).parse(payload)
    assert isinstance(result, OxygenSaturation)
    assert result.value == float(spo2)
