# SPDX-License-Identifier: AGPL-3.0-or-later
"""Device user ID handling in the blood-pressure and weight parsers (issue #8, ADR-0004).

A multi-user cuff or scale tags each reading with a one-byte user ID. The parsers
decode it only to compare with the configured ``VOF_DEVICE_USER_ID`` and keep the
outcome (``device_user``), never the ID. The payloads here put the user-ID byte
after every optional field that precedes it, so a wrong offset shows up as a wrong
outcome.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from vitals_on_fhir.adapters.bp_parser import BloodPressureMeasurementParser
from vitals_on_fhir.adapters.weight_parser import WeightMeasurementParser
from vitals_on_fhir.cli import _resolve_adapter
from vitals_on_fhir.config import Settings
from vitals_on_fhir.vitals import BloodPressure, BodyWeight, DeviceUserMatch

_NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
_TIMESTAMP = (2026).to_bytes(2, "little") + bytes([10, 6, 8, 30, 0])
_UNKNOWN_USER = 0xFF


def _bp_payload(user_id: int | None, *, timestamp: bool = True, pulse: bool = True) -> bytes:
    """Blood Pressure Measurement: 120/80 mmHg, optional timestamp, pulse rate and user ID."""
    flags = (
        (0x02 if timestamp else 0) | (0x04 if pulse else 0) | (0x08 if user_id is not None else 0)
    )
    payload = bytes([flags]) + (120).to_bytes(2, "little") + (80).to_bytes(2, "little")
    payload += (93).to_bytes(2, "little")  # MAP
    if timestamp:
        payload += _TIMESTAMP
    if pulse:
        payload += (72).to_bytes(2, "little")
    if user_id is not None:
        payload += bytes([user_id])
    return payload


def _weight_payload(user_id: int | None, *, timestamp: bool = True, bmi: bool = True) -> bytes:
    """Weight Measurement: 70 kg (SI), optional timestamp, user ID and BMI + height."""
    flags = (0x02 if timestamp else 0) | (0x04 if user_id is not None else 0) | (0x08 if bmi else 0)
    payload = bytes([flags]) + (14000).to_bytes(2, "little")
    if timestamp:
        payload += _TIMESTAMP
    if user_id is not None:
        payload += bytes([user_id])
    if bmi:
        payload += bytes([0xEE, 0x00, 0xEE, 0x06])  # BMI + height, length-accounted only
    return payload


def _parse_bp(payload: bytes, configured: int | None) -> BloodPressure:
    reading = BloodPressureMeasurementParser(
        "bp", now=lambda: _NOW, device_user_id=configured
    ).parse(payload)
    assert isinstance(reading, BloodPressure)
    return reading


def _parse_weight(payload: bytes, configured: int | None) -> BodyWeight:
    reading = WeightMeasurementParser("scale", now=lambda: _NOW, device_user_id=configured).parse(
        payload
    )
    assert isinstance(reading, BodyWeight)
    return reading


@pytest.mark.parametrize(
    ("reported", "configured", "expected"),
    [
        (None, None, None),
        (None, 3, None),
        (3, None, DeviceUserMatch.NOT_CONFIGURED),
        (3, 3, DeviceUserMatch.MATCH),
        (4, 3, DeviceUserMatch.MISMATCH),
        (_UNKNOWN_USER, 3, DeviceUserMatch.MISMATCH),
    ],
)
def test_parsers_compare_the_device_user(
    reported: int | None, configured: int | None, expected: DeviceUserMatch | None
) -> None:
    """Both parsers report the same outcome for the same reported and configured IDs."""
    assert _parse_bp(_bp_payload(reported), configured).device_user is expected
    assert _parse_weight(_weight_payload(reported), configured).device_user is expected


@pytest.mark.parametrize("timestamp", [True, False])
@pytest.mark.parametrize("other", [True, False])
def test_user_id_offset_follows_the_optional_fields(timestamp: bool, other: bool) -> None:
    """The user ID is read after the timestamp (and BP pulse rate), whichever are present."""
    bp = _bp_payload(9, timestamp=timestamp, pulse=other)
    assert _parse_bp(bp, 9).device_user is DeviceUserMatch.MATCH
    weight = _weight_payload(9, timestamp=timestamp, bmi=other)
    assert _parse_weight(weight, 9).device_user is DeviceUserMatch.MATCH


def test_the_user_id_is_not_kept_on_the_reading() -> None:
    """No field of a parsed reading holds the user ID."""
    for reading in (_parse_bp(_bp_payload(173), 173), _parse_weight(_weight_payload(173), 173)):
        values = [getattr(reading, f.name) for f in dataclasses.fields(reading)]
        assert 173 not in values
        assert "173" not in repr(reading)


@pytest.mark.parametrize("adapter", ["bp", "weight"])
def test_cli_forwards_the_configured_user_to_the_parser(adapter: str) -> None:
    """``VOF_DEVICE_USER_ID`` reaches the parser of the BP and weight adapters."""
    built = _resolve_adapter(adapter, Settings(device_user_id=3))
    parser = built._build_parser()  # type: ignore[attr-defined]
    payload = _bp_payload(4) if adapter == "bp" else _weight_payload(4)
    reading = parser.parse(payload)
    assert reading is not None
    assert reading.device_user is DeviceUserMatch.MISMATCH  # type: ignore[attr-defined]
