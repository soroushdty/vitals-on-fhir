# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared fixtures for adapter tests, including Heart Rate Measurement payloads.

The byte layouts below follow the Bluetooth SIG Heart Rate Measurement
characteristic (0x2A37). The flags byte (offset 0) declares the value format
and which optional fields follow; see ``docs/`` for the specification citation.

Flags-byte bits used here:
- bit 0 (0x01): value format — 0 = uint8, 1 = uint16 little-endian
- bit 1 (0x02): sensor-contact detected (meaningful only when bit 2 set)
- bit 2 (0x04): sensor-contact status supported
- bit 3 (0x08): energy-expended field present (2 bytes)
- bit 4 (0x10): RR-interval field(s) present (tail, 2 bytes each)
"""

from __future__ import annotations

import pytest


@pytest.fixture
def hr_payload_uint8_contact() -> bytes:
    """Valid payload: uint8 HR value 72, sensor contact supported and detected.

    flags = 0x06 (sensor-contact supported + detected), value = 72 (0x48).
    """
    return bytes([0x06, 72])


@pytest.fixture
def hr_payload_uint8_no_contact() -> bytes:
    """Valid payload: uint8 HR value 80, sensor contact supported but not detected.

    flags = 0x04 (sensor-contact supported, not detected), value = 80 (0x50).
    """
    return bytes([0x04, 80])


@pytest.fixture
def hr_payload_uint16_contact() -> bytes:
    """Valid payload: uint16 HR value 300, sensor contact supported and detected.

    flags = 0x07 (uint16 + sensor-contact supported + detected),
    value = 300 (0x012C) little-endian = 0x2C, 0x01.
    """
    return bytes([0x07, 0x2C, 0x01])


@pytest.fixture
def hr_payload_uint16_no_contact() -> bytes:
    """Valid payload: uint16 HR value 310, sensor contact supported but not detected.

    flags = 0x05 (uint16 + sensor-contact supported, not detected),
    value = 310 (0x0136) little-endian = 0x36, 0x01.
    """
    return bytes([0x05, 0x36, 0x01])


@pytest.fixture
def hr_payload_with_rr() -> bytes:
    """Valid payload with RR intervals: uint8 HR value 65, contact detected, one RR interval.

    flags = 0x16 (RR present + sensor-contact supported + detected),
    value = 65 (0x41), followed by one RR-interval value 0x03C0 little-endian.
    RR intervals are the tail and do not change the decoded heart-rate value.
    """
    return bytes([0x16, 65, 0xC0, 0x03])


@pytest.fixture
def hr_payload_truncated() -> bytes:
    """Truncated payload: flags declare uint16 but only one value byte is present.

    flags = 0x01 (uint16) requires two value bytes; only one is supplied, so the
    parser must return ``None``.
    """
    return bytes([0x01, 0x48])


@pytest.fixture
def hr_payload_empty() -> bytes:
    """Zero-length payload; the parser must return ``None``."""
    return b""
