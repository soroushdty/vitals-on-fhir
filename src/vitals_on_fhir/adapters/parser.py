# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parser for the Bluetooth Heart Rate Measurement characteristic (0x2A37).

Byte-level decoding logic lives in pure module-level functions that are total
(they never raise, validating length and returning sentinels instead). The
``HeartRateMeasurementParser`` class delegates to them and assembles the
resulting ``HeartRate`` domain object, supplying the ``device_id`` and the
timestamp so the decode functions stay pure and clock/identity-free.

This module depends only on the ``vitals`` package and the Python standard
library. See ``docs/`` for the Bluetooth SIG specification citation.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import NamedTuple

from vitals_on_fhir.adapters.ble import GattCharacteristicParser
from vitals_on_fhir.vitals.base import VitalSign
from vitals_on_fhir.vitals.builtin.heart_rate import HeartRate

# Heart Rate Measurement flags byte (offset 0) bit positions.
_FLAG_VALUE_FORMAT_UINT16 = 0x01  # bit 0: 0 -> uint8 value, 1 -> uint16 LE value
_FLAG_SENSOR_CONTACT_DETECTED = 0x02  # bit 1: sensor-contact detected (meaningful iff bit 2 set)
_FLAG_SENSOR_CONTACT_SUPPORTED = 0x04  # bit 2: sensor-contact status supported
_FLAG_ENERGY_EXPENDED_PRESENT = 0x08  # bit 3: energy-expended field present (2 bytes)
_FLAG_RR_INTERVAL_PRESENT = 0x10  # bit 4: RR-interval field(s) present (tail)

_ENERGY_EXPENDED_SIZE = 2  # bytes


class HrFlags(NamedTuple):
    """Decoded, immutable view of the relevant Heart Rate Measurement flag bits.

    Internal to this module; not exported from the ``adapters`` package.
    """

    value_is_uint16: bool
    sensor_contact_supported: bool
    sensor_contact_detected: bool
    energy_expended_present: bool
    rr_interval_present: bool


def parse_flags(byte: int) -> HrFlags:
    """Decode the five relevant bits of the flags byte into an ``HrFlags`` record."""
    return HrFlags(
        value_is_uint16=bool(byte & _FLAG_VALUE_FORMAT_UINT16),
        sensor_contact_supported=bool(byte & _FLAG_SENSOR_CONTACT_SUPPORTED),
        sensor_contact_detected=bool(byte & _FLAG_SENSOR_CONTACT_DETECTED),
        energy_expended_present=bool(byte & _FLAG_ENERGY_EXPENDED_PRESENT),
        rr_interval_present=bool(byte & _FLAG_RR_INTERVAL_PRESENT),
    )


def hr_value_size(flags: HrFlags) -> int:
    """Return the size in bytes of the heart-rate value field (``2`` for uint16, else ``1``)."""
    return 2 if flags.value_is_uint16 else 1


def required_length(flags: HrFlags) -> int:
    """Return the minimum payload length the flags byte declares.

    Accounts for the flags byte, the heart-rate value, and the energy-expended
    field when present. RR intervals occupy the tail and are not required to
    decode the heart-rate value, so they do not add to the required length.
    """
    length = 1 + hr_value_size(flags)
    if flags.energy_expended_present:
        length += _ENERGY_EXPENDED_SIZE
    return length


def decode_hr_value(data: bytes, flags: HrFlags) -> int:
    """Read the heart-rate value at offset 1 as uint8 or uint16 little-endian.

    The caller must have already checked the payload is long enough via
    ``required_length``; this function assumes the value bytes are present.
    """
    if flags.value_is_uint16:
        return int.from_bytes(data[1:3], byteorder="little", signed=False)
    return data[1]


def decode_sensor_contact(flags: HrFlags) -> bool | None:
    """Map the sensor-contact flag bits to a tri-state value.

    Returns ``None`` when sensor-contact status is not supported, otherwise the
    reported boolean.
    """
    if not flags.sensor_contact_supported:
        return None
    return flags.sensor_contact_detected


class HeartRateMeasurementParser(GattCharacteristicParser):
    """Parses raw GATT 0x2A37 (Heart Rate Measurement) notification payloads.

    Decodes the flags byte to determine whether the heart-rate value is uint8
    or uint16, extracts sensor-contact status, and returns a ``HeartRate``
    domain object. Returns ``None`` for malformed payloads so the adapter can
    drop them silently.
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
                ``effective`` time. Defaults to ``datetime.now(UTC)``. Injectable
                so tests can pin the clock.
        """
        self._device_id = device_id
        self._now: Callable[[], datetime] = now if now is not None else (lambda: datetime.now(UTC))

    @property
    def device_id(self) -> str:
        """Device identifier assigned to readings produced by this parser."""
        return self._device_id

    def parse(self, data: bytes) -> VitalSign | None:
        """Parse a raw Heart Rate Measurement payload.

        Returns a ``HeartRate`` instance on success, or ``None`` if the payload
        is empty, too short for the fields its flags byte declares, or otherwise
        malformed.
        """
        if len(data) < 1:
            return None
        flags = parse_flags(data[0])
        if len(data) < required_length(flags):
            return None
        value = decode_hr_value(data, flags)
        sensor_contact = decode_sensor_contact(flags)
        return HeartRate(
            effective=self._now(),
            device_id=self._device_id,
            value=float(value),
            sensor_contact=sensor_contact,
        )
