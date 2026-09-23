# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the shared IEEE-11073 32-bit FLOAT decoder (``adapters/sfloat.py``).

Kept separate from the 16-bit SFLOAT decoder tests (``test_sfloat.py``): the
32-bit FLOAT uses an 8-bit signed exponent and a 24-bit signed mantissa, with
its own reserved special-value set. Covers a Hypothesis round-trip over the
representable (non-reserved) mantissa/exponent space, each reserved mantissa
returning ``None``, and negative-exponent / negative-mantissa examples.

Requirements: FR-TEMP-2, NFR-TEMP-6.
"""

from __future__ import annotations

import math

from hypothesis import given, settings
from hypothesis import strategies as st

from vitals_on_fhir.adapters.sfloat import FLOAT_SIZE, decode_float

# Reserved 24-bit mantissa values (NaN, NRes, +INF, -INF, reserved).
_RESERVED_MANTISSAS = (0x007FFFFF, 0x00800000, 0x007FFFFE, 0x00800002, 0x00800001)


def _encode_float(mantissa: int, exponent: int = 0) -> bytes:
    """Encode a 32-bit IEEE-11073 FLOAT (8-bit exponent, 24-bit mantissa), little-endian."""
    raw = ((exponent & 0xFF) << 24) | (mantissa & 0x00FFFFFF)
    return raw.to_bytes(FLOAT_SIZE, byteorder="little", signed=False)


def test_float_size_is_four_bytes() -> None:
    """The exported FLOAT size constant is four bytes."""
    assert FLOAT_SIZE == 4


def test_decode_float_reserved_values_return_none() -> None:
    """Each of the five FLOAT reserved mantissas decodes to ``None``."""
    for reserved in _RESERVED_MANTISSAS:
        assert decode_float(_encode_float(reserved, 0), 0) is None


def test_decode_float_negative_exponent() -> None:
    """A negative exponent scales the mantissa by a power of ten."""
    # 3705 x 10^-2 = 37.05
    decoded = decode_float(_encode_float(3705, -2), 0)
    assert decoded is not None
    assert math.isclose(decoded, 37.05, rel_tol=1e-12, abs_tol=0.0)


def test_decode_float_negative_mantissa() -> None:
    """A 24-bit mantissa at or above 0x800000 is sign-extended negative."""
    # -1 mantissa (0xFFFFFF) at exponent 0.
    assert decode_float(_encode_float(0xFFFFFF, 0), 0) == -1.0
    # -1000 x 10^-1 = -100.0 using a negative mantissa and a negative exponent.
    assert decode_float(_encode_float(-1000, -1), 0) == -100.0


def test_decode_float_respects_offset() -> None:
    """Decoding reads four bytes starting at the given offset."""
    payload = b"\xff" + _encode_float(3700, -2)
    assert decode_float(payload, 1) == 37.0


# Feature: body-temperature, Property 1: FLOAT decode round-trip
@given(
    mantissa=st.integers(min_value=0, max_value=0x00FFFFFF),
    exponent=st.integers(min_value=-128, max_value=127),
)
@settings(max_examples=200)
def test_decode_float_round_trip(mantissa: int, exponent: int) -> None:
    """Encoding a (mantissa, exponent) then decoding recovers the intended value.

    Reserved mantissas decode to ``None``; every other combination decodes to
    the sign-extended 24-bit mantissa scaled by ten to the sign-extended 8-bit
    exponent, with correct signs.
    """
    decoded = decode_float(_encode_float(mantissa, exponent), 0)
    if mantissa in _RESERVED_MANTISSAS:
        assert decoded is None
        return

    signed_mantissa = mantissa - 0x1000000 if mantissa >= 0x800000 else mantissa
    expected = float(signed_mantissa) * (10.0**exponent)

    assert decoded is not None
    assert math.isclose(decoded, expected, rel_tol=1e-12, abs_tol=0.0)
    # Sign correctness.
    assert (decoded > 0) == (signed_mantissa > 0)
    assert (decoded < 0) == (signed_mantissa < 0)
