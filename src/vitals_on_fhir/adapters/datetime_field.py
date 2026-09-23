# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared org.bluetooth date-time (7-byte) decoding for GATT measurement parsers.

Several standard Bluetooth measurement characteristics carry an optional
org.bluetooth date-time field — a 7-byte structure of year (uint16 little-endian)
followed by month, day, hours, minutes, and seconds (each uint8) — including the
Blood Pressure Measurement (``0x2A35``) and the Temperature Measurement
(``0x2A1C``) characteristics. This module holds that decoding once, as a pure
function usable by more than one parser, so the calendar decode is not duplicated
across parsers.

Timezone convention: the field carries no timezone. Per the project's
local-home-monitoring assumption, a decoded device timestamp is interpreted as
the host's local time and returned timezone-aware (documented in
``docs/protocol-blood-pressure-measurement.md``).

Depends only on the Python standard library; introduces no cross-package
dependency (it lives in the ``adapters`` package alongside its callers).
"""

from __future__ import annotations

from datetime import datetime

TIMESTAMP_SIZE = 7  # bytes


def decode_timestamp(data: bytes, offset: int) -> datetime | None:
    """Decode the 7-byte org.bluetooth date-time at *offset* as host local time.

    Layout: year (uint16 little-endian), month, day, hours, minutes, seconds
    (each uint8). The field carries no timezone; the value is interpreted as the
    host's local time and returned timezone-aware with the host's local offset,
    per the local-home-monitoring assumption.

    Returns ``None`` if the fields do not form a valid calendar date-time (the
    org.bluetooth date-time allows "unknown" fields encoded as zero, which are
    not a usable timestamp). The caller must ensure at least seven bytes are
    available at *offset*.
    """
    year = int.from_bytes(data[offset : offset + 2], byteorder="little", signed=False)
    month = data[offset + 2]
    day = data[offset + 3]
    hour = data[offset + 4]
    minute = data[offset + 5]
    second = data[offset + 6]
    try:
        naive = datetime(year, month, day, hour, minute, second)  # noqa: DTZ001 - local by design
    except ValueError:
        return None
    # Attach the host's local timezone offset, making the value tz-aware.
    return naive.astimezone()
