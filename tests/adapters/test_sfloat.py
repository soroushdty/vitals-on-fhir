# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the shared IEEE-11073 16-bit SFLOAT decoder (``adapters/sfloat.py``).

Covers normal integer values, negative exponent and negative mantissa scaling,
each reserved mantissa returning ``None``, and a Hypothesis round-trip over the
representable (non-reserved) mantissa/exponent space.

Requirements: FR-SPO2-2, NFR-SPO2-2, NFR-SPO2-6.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from vitals_on_fhir.adapters.sfloat import SFLOAT_SIZE, decode_sfloat

# Reserved 12-bit mantissa values (NaN, NRes, +INF, -INF, reserved).
_RESERVED_MANTISSAS = (0x07FF, 0x0800, 0x07FE, 0x0802, 0x0801)


def _encode_sfloat(mantissa: int, exponent: int = 0) -> bytes:
    """Encode a 16-bit IEEE-11073 SFLOAT (4-bit exponent, 12-bit mantissa), little-endian."""
    raw = ((exponent & 0x0F) << 12) | (mantissa & 0x0FFF)
    return raw.to_bytes(SFLOAT_SIZE, byteorder="little", signed=False)


def test_sfloat_size_is_two_bytes() -> None:
    """The exported SFLOAT size constant is two bytes."""
    assert SFLOAT_SIZE == 2


def test_decode_sfloat_integer_value() -> None:
    """A mantissa with exponent 0 decodes to that integer value."""
    assert decode_sfloat(_encode_sfloat(120, 0), 0) == 120.0


def test_decode_sfloat_negative_exponent() -> None:
    """A negative exponent scales the mantissa by a power of ten."""
    # 985 x 10^-1 = 98.5
    assert decode_sfloat(_encode_sfloat(985, -1), 0) == 98.5


def test_decode_sfloat_negative_mantissa() -> None:
    """A 12-bit mantissa at or above 0x0800 is sign-extended negative."""
    # -1 mantissa (0x0FFF) at exponent 0.
    assert decode_sfloat(_encode_sfloat(0x0FFF, 0), 0) == -1.0
    # -256 x 10^1 using mantissa 0x0F00 (= -256) and exponent 1.
    assert decode_sfloat(_encode_sfloat(0x0F00, 1), 0) == -2560.0


def test_decode_sfloat_respects_offset() -> None:
    """Decoding reads two bytes starting at the given offset."""
    payload = b"\xff" + _encode_sfloat(120, 0)
    assert decode_sfloat(payload, 1) == 120.0


def test_decode_sfloat_reserved_values_return_none() -> None:
    """Reserved mantissas (NaN, NRes, ±INF, reserved) decode to ``None``."""
    for reserved in _RESERVED_MANTISSAS:
        assert decode_sfloat(_encode_sfloat(reserved, 0), 0) is None


@given(
    mantissa=st.integers(min_value=0, max_value=0x0FFF),
    exponent=st.integers(min_value=-8, max_value=7),
)
@settings(max_examples=200)
def test_decode_sfloat_round_trip(mantissa: int, exponent: int) -> None:
    """Encoding a (mantissa, exponent) then decoding recovers the intended value.

    Reserved mantissas decode to ``None``; every other combination decodes to
    the sign-extended mantissa scaled by ten to the sign-extended exponent.
    """
    decoded = decode_sfloat(_encode_sfloat(mantissa, exponent), 0)
    if mantissa in _RESERVED_MANTISSAS:
        assert decoded is None
        return

    signed_mantissa = mantissa - 0x1000 if mantissa >= 0x0800 else mantissa
    assert decoded == float(signed_mantissa) * (10.0**exponent)
