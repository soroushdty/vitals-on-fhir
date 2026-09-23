# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared IEEE-11073 16-bit SFLOAT decoding for GATT measurement parsers.

Several standard Bluetooth measurement characteristics encode numeric values as
IEEE-11073-20601 16-bit SFLOATs (a 4-bit signed exponent and a 12-bit signed
mantissa), including the Blood Pressure Measurement (``0x2A35``) and the Pulse
Oximeter measurement characteristics. This module holds that decoding once, as
a pure function usable by more than one parser, so the encoding is not
duplicated across parsers.

Protocol source: IEEE-11073-20601 (Personal Health Data — Optimized Exchange
Protocol), which defines the FLOAT/SFLOAT medical value representations and the
reserved special values (NaN, NRes, +INFINITY, -INFINITY, reserved). See also
``docs/protocol-blood-pressure-measurement.md``.

Depends only on the Python standard library; introduces no cross-package
dependency (it lives in the ``adapters`` package alongside its callers).
"""

from __future__ import annotations

SFLOAT_SIZE = 2  # bytes
FLOAT_SIZE = 4  # bytes

# Reserved 12-bit mantissa values that do not represent a usable number.
# (NaN, NRes, +INFINITY, -INFINITY, and the reserved value.)
_SFLOAT_RESERVED_MANTISSAS = frozenset({0x07FF, 0x0800, 0x07FE, 0x0802, 0x0801})

# Reserved 24-bit mantissa values that do not represent a usable number.
# (NaN, NRes, +INFINITY, -INFINITY, and the reserved value.) These are the
# 32-bit FLOAT analogues of the 16-bit SFLOAT reserved set above.
_FLOAT_RESERVED_MANTISSAS = frozenset(
    {0x007FFFFF, 0x00800000, 0x007FFFFE, 0x00800002, 0x00800001}
)


def decode_sfloat(data: bytes, offset: int) -> float | None:
    """Decode a 16-bit IEEE-11073 SFLOAT at *offset* (little-endian).

    An SFLOAT is a 4-bit signed exponent (high nibble) and a 12-bit signed
    mantissa. Reserved mantissa values (NaN, NRes, ±INFINITY, reserved) do not
    represent a usable number and yield ``None`` so the caller can drop the
    reading.

    The caller must ensure at least two bytes are available at *offset*.
    """
    raw = int.from_bytes(data[offset : offset + SFLOAT_SIZE], byteorder="little", signed=False)
    mantissa = raw & 0x0FFF
    exponent = raw >> 12

    if mantissa in _SFLOAT_RESERVED_MANTISSAS:
        return None

    # Sign-extend the 12-bit mantissa and the 4-bit exponent.
    if mantissa >= 0x0800:
        mantissa -= 0x1000
    if exponent >= 0x0008:
        exponent -= 0x10

    return float(mantissa) * (10.0**exponent)


def decode_float(data: bytes, offset: int) -> float | None:
    """Decode a 32-bit IEEE-11073 FLOAT at *offset* (little-endian).

    A FLOAT is an 8-bit signed exponent (high byte) and a 24-bit signed
    mantissa (low three bytes). Reserved mantissa values (NaN, NRes, ±INFINITY,
    reserved) do not represent a usable number and yield ``None`` so the caller
    can drop the reading. Distinct from :func:`decode_sfloat`'s 16-bit form,
    which uses a 4-bit exponent and a 12-bit mantissa.

    The caller must ensure at least four bytes are available at *offset*.
    """
    raw = int.from_bytes(data[offset : offset + FLOAT_SIZE], byteorder="little", signed=False)
    mantissa = raw & 0x00FFFFFF
    exponent = raw >> 24

    if mantissa in _FLOAT_RESERVED_MANTISSAS:
        return None

    # Sign-extend the 24-bit mantissa and the 8-bit exponent.
    if mantissa >= 0x800000:
        mantissa -= 0x1000000
    if exponent >= 0x80:
        exponent -= 0x100

    return float(mantissa) * (10.0**exponent)
