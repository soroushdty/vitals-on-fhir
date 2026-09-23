# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parser for the Bluetooth Blood Pressure Measurement characteristic (GATT 0x2A35).

Decodes a Blood Pressure Measurement notification into a
:class:`~vitals_on_fhir.vitals.BloodPressure` domain object. The byte-level
decoding — the flags byte, IEEE-11073 16-bit SFLOAT values, the optional
date-time field, and unit normalization — lives in pure functions that
:class:`BloodPressureMeasurementParser` delegates to, mirroring the heart-rate
parser. The shared IEEE-11073 SFLOAT decoding is imported from
:mod:`vitals_on_fhir.adapters.sfloat` (used by both this and the pulse-oximeter
parser), and the shared org.bluetooth date-time decoding is imported from
:mod:`vitals_on_fhir.adapters.datetime_field` (used by both this and the
temperature parser); both are re-exported here for backward compatibility.

Protocol source: Bluetooth SIG Blood Pressure Service / Blood Pressure
Measurement characteristic (see ``docs/protocol-blood-pressure-measurement.md``).
Systolic, diastolic, and mean-arterial-pressure are three consecutive SFLOATs;
only systolic and diastolic are used (MAP is device-derived and not modelled).

Timezone note: the characteristic's date-time field carries no timezone. Per the
project's local-home-monitoring assumption, a decoded device timestamp is
interpreted as the host's local time and returned timezone-aware.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import NamedTuple

from vitals_on_fhir.adapters.ble import GattCharacteristicParser
from vitals_on_fhir.adapters.datetime_field import TIMESTAMP_SIZE, decode_timestamp
from vitals_on_fhir.adapters.sfloat import SFLOAT_SIZE, decode_sfloat
from vitals_on_fhir.vitals.base import VitalSign
from vitals_on_fhir.vitals.builtin.blood_pressure import BloodPressure

__all__ = [
    "BloodPressureMeasurementParser",
    "BpFlags",
    "decode_sfloat",
    "decode_timestamp",
    "kpa_to_mmhg",
    "parse_bp_flags",
    "required_length",
]

# Blood Pressure Measurement flags byte (offset 0) bit positions.
_FLAG_UNIT_KPA = 0x01  # bit 0: 0 -> mmHg, 1 -> kPa
_FLAG_TIMESTAMP_PRESENT = 0x02  # bit 1: date-time field present (7 bytes)
_FLAG_PULSE_RATE_PRESENT = 0x04  # bit 2: pulse-rate SFLOAT present (2 bytes)
_FLAG_USER_ID_PRESENT = 0x08  # bit 3: user-id field present (1 byte)
_FLAG_MEASUREMENT_STATUS_PRESENT = 0x10  # bit 4: measurement-status field present (2 bytes)

_TIMESTAMP_SIZE = TIMESTAMP_SIZE  # bytes (shared org.bluetooth date-time size)
_PULSE_RATE_SIZE = 2  # bytes
_USER_ID_SIZE = 1  # bytes
_MEASUREMENT_STATUS_SIZE = 2  # bytes

# Three SFLOATs (systolic, diastolic, MAP) follow the flags byte.
_SYSTOLIC_OFFSET = 1
_DIASTOLIC_OFFSET = 3
_MAP_OFFSET = 5

# 1 kPa expressed in mmHg (for unit normalization).
_MMHG_PER_KPA = 7.50062


class BpFlags(NamedTuple):
    """Decoded view of the Blood Pressure Measurement flags byte.

    Internal to this module; not exported from the ``adapters`` package.
    """

    unit_is_kpa: bool
    timestamp_present: bool
    pulse_rate_present: bool
    user_id_present: bool
    measurement_status_present: bool


def parse_bp_flags(byte: int) -> BpFlags:
    """Decode the five relevant bits of the flags byte into a ``BpFlags`` record."""
    return BpFlags(
        unit_is_kpa=bool(byte & _FLAG_UNIT_KPA),
        timestamp_present=bool(byte & _FLAG_TIMESTAMP_PRESENT),
        pulse_rate_present=bool(byte & _FLAG_PULSE_RATE_PRESENT),
        user_id_present=bool(byte & _FLAG_USER_ID_PRESENT),
        measurement_status_present=bool(byte & _FLAG_MEASUREMENT_STATUS_PRESENT),
    )


def required_length(flags: BpFlags) -> int:
    """Return the minimum payload length the flags byte declares.

    Accounts for the flags byte, the three mandatory SFLOATs (systolic,
    diastolic, MAP), and each optional field the flags declare present.
    """
    length = 1 + 3 * SFLOAT_SIZE
    if flags.timestamp_present:
        length += _TIMESTAMP_SIZE
    if flags.pulse_rate_present:
        length += _PULSE_RATE_SIZE
    if flags.user_id_present:
        length += _USER_ID_SIZE
    if flags.measurement_status_present:
        length += _MEASUREMENT_STATUS_SIZE
    return length


def kpa_to_mmhg(value: float) -> float:
    """Convert a pressure in kPa to mmHg."""
    return value * _MMHG_PER_KPA


class BloodPressureMeasurementParser(GattCharacteristicParser):
    """Parses raw GATT 0x2A35 (Blood Pressure Measurement) notification payloads.

    Decodes the flags byte, the systolic and diastolic SFLOAT values (in mmHg,
    normalizing from kPa when the flags indicate), and the optional measurement
    timestamp, returning a ``BloodPressure`` domain object. Returns ``None`` for
    malformed payloads (too short, or a reserved/unusable SFLOAT for either
    used value) so the adapter can drop them silently.
    """

    def __init__(
        self,
        device_id: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        """Create a parser bound to a device identity and clock.

        Args:
            device_id: Identifier linking parsed readings to a Device resource.
            now: Callable returning a timezone-aware timestamp for the reading's
                ``effective`` time when the payload carries no timestamp.
                Defaults to a local-aware ``datetime.now().astimezone()``.
                Injectable so tests can pin the clock.
        """
        self._device_id = device_id
        self._now: Callable[[], datetime] = (
            now if now is not None else (lambda: datetime.now().astimezone())
        )

    @property
    def device_id(self) -> str:
        """Device identifier assigned to readings produced by this parser."""
        return self._device_id

    def parse(self, data: bytes) -> VitalSign | None:
        """Parse a raw Blood Pressure Measurement payload.

        Returns a ``BloodPressure`` instance on success, or ``None`` if the
        payload is empty, too short for the fields its flags byte declares, or
        carries a reserved/unusable SFLOAT for the systolic or diastolic value.
        """
        if len(data) < 1:
            return None
        flags = parse_bp_flags(data[0])
        if len(data) < required_length(flags):
            return None

        systolic = decode_sfloat(data, _SYSTOLIC_OFFSET)
        diastolic = decode_sfloat(data, _DIASTOLIC_OFFSET)
        if systolic is None or diastolic is None:
            return None

        if flags.unit_is_kpa:
            systolic = kpa_to_mmhg(systolic)
            diastolic = kpa_to_mmhg(diastolic)

        if flags.timestamp_present:
            # Timestamp follows the three mandatory SFLOATs (offset 7).
            effective = decode_timestamp(data, 1 + 3 * SFLOAT_SIZE)
            if effective is None:
                return None
        else:
            effective = self._now()

        return BloodPressure(
            effective=effective,
            device_id=self._device_id,
            systolic=systolic,
            diastolic=diastolic,
        )
