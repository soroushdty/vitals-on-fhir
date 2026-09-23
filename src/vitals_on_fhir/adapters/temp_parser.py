# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parser for the Bluetooth Temperature Measurement characteristic (GATT 0x2A1C).

Decodes a Temperature Measurement indication into a
:class:`~vitals_on_fhir.vitals.BodyTemperature` domain object. The byte-level
decoding — the flags byte, the IEEE-11073 32-bit FLOAT temperature value, the
optional org.bluetooth date-time field, and Fahrenheit unit normalization —
lives in pure functions that :class:`TemperatureMeasurementParser` delegates to,
mirroring the heart-rate and blood-pressure parsers. The shared IEEE-11073
32-bit FLOAT decoding is imported from :mod:`vitals_on_fhir.adapters.sfloat`, and
the shared org.bluetooth date-time decoding from
:mod:`vitals_on_fhir.adapters.datetime_field` (used by both this and the
blood-pressure parser).

Protocol source: Bluetooth SIG Health Thermometer Service (``0x1809``) /
Temperature Measurement characteristic (``0x2A1C``); see
``docs/protocol-body-temperature-measurement.md``. The temperature value is a
single 32-bit FLOAT; the optional temperature-type field is length-accounted
only and not modelled in the reading.

Timezone note: the characteristic's optional date-time field carries no
timezone. Per the project's local-home-monitoring assumption, a decoded device
timestamp is interpreted as the host's local time and returned timezone-aware,
matching the blood-pressure convention.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import NamedTuple

from vitals_on_fhir.adapters.ble import GattCharacteristicParser
from vitals_on_fhir.adapters.datetime_field import TIMESTAMP_SIZE, decode_timestamp
from vitals_on_fhir.adapters.sfloat import FLOAT_SIZE, decode_float
from vitals_on_fhir.vitals.base import VitalSign
from vitals_on_fhir.vitals.builtin.body_temperature import BodyTemperature

__all__ = [
    "TemperatureMeasurementParser",
    "TempFlags",
    "fahrenheit_to_celsius",
    "parse_temp_flags",
    "required_length",
]

_logger = logging.getLogger(__name__)

# Temperature Measurement flags byte (offset 0) bit positions.
_FLAG_UNIT_FAHRENHEIT = 0x01  # bit 0: 0 -> Celsius, 1 -> Fahrenheit
_FLAG_TIMESTAMP_PRESENT = 0x02  # bit 1: date-time field present (7 bytes)
_FLAG_TEMPERATURE_TYPE_PRESENT = 0x04  # bit 2: temperature-type field present (1 byte)

_TEMPERATURE_TYPE_SIZE = 1  # bytes (length-accounted only, not modelled)

# The mandatory temperature FLOAT follows the flags byte (offset 1); an optional
# timestamp follows the FLOAT (offset 1 + FLOAT_SIZE).
_TEMPERATURE_OFFSET = 1
_TIMESTAMP_OFFSET = _TEMPERATURE_OFFSET + FLOAT_SIZE


class TempFlags(NamedTuple):
    """Decoded view of the Temperature Measurement flags byte.

    Internal to this module; not exported from the ``adapters`` package.
    """

    unit_is_fahrenheit: bool
    timestamp_present: bool
    temperature_type_present: bool


def parse_temp_flags(byte: int) -> TempFlags:
    """Decode the three relevant bits of the flags byte into a ``TempFlags`` record."""
    return TempFlags(
        unit_is_fahrenheit=bool(byte & _FLAG_UNIT_FAHRENHEIT),
        timestamp_present=bool(byte & _FLAG_TIMESTAMP_PRESENT),
        temperature_type_present=bool(byte & _FLAG_TEMPERATURE_TYPE_PRESENT),
    )


def required_length(flags: TempFlags) -> int:
    """Return the minimum payload length the flags byte declares.

    Accounts for the flags byte, the mandatory temperature FLOAT, and each
    optional field the flags declare present (timestamp, temperature type). The
    temperature-type field is length-accounted only; it is never decoded.
    """
    length = 1 + FLOAT_SIZE
    if flags.timestamp_present:
        length += TIMESTAMP_SIZE
    if flags.temperature_type_present:
        length += _TEMPERATURE_TYPE_SIZE
    return length


def fahrenheit_to_celsius(value: float) -> float:
    """Convert a temperature in degrees Fahrenheit to degrees Celsius."""
    return (value - 32) * 5 / 9


class TemperatureMeasurementParser(GattCharacteristicParser):
    """Parses raw GATT 0x2A1C (Temperature Measurement) indication payloads.

    Decodes the flags byte and the mandatory temperature 32-bit FLOAT (in
    degrees Celsius, normalizing from Fahrenheit when the flags indicate), and
    the optional measurement timestamp, returning a ``BodyTemperature`` domain
    object. Returns ``None`` for malformed payloads (too short for the fields
    the flags declare, a reserved/unusable temperature FLOAT, or a declared
    timestamp that is not a valid calendar date-time) so the adapter can drop
    them silently, logging at ``DEBUG`` with the byte length only, never the
    value.
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
        """Parse a raw Temperature Measurement payload.

        Returns a ``BodyTemperature`` instance on success, or ``None`` if the
        payload is empty, too short for the fields its flags byte declares,
        carries a reserved/unusable temperature FLOAT, or declares a timestamp
        that is not a valid calendar date-time.
        """
        if len(data) < 1:
            _logger.debug("Dropping empty temperature payload (%d bytes)", len(data))
            return None
        flags = parse_temp_flags(data[0])
        if len(data) < required_length(flags):
            _logger.debug("Dropping short temperature payload (%d bytes)", len(data))
            return None

        temp = decode_float(data, _TEMPERATURE_OFFSET)
        if temp is None:
            _logger.debug(
                "Dropping temperature payload with reserved/unusable FLOAT (%d bytes)",
                len(data),
            )
            return None

        if flags.unit_is_fahrenheit:
            temp = fahrenheit_to_celsius(temp)

        if flags.timestamp_present:
            effective = decode_timestamp(data, _TIMESTAMP_OFFSET)
            if effective is None:
                _logger.debug(
                    "Dropping temperature payload with invalid timestamp (%d bytes)",
                    len(data),
                )
                return None
        else:
            effective = self._now()

        return BodyTemperature(
            effective=effective,
            device_id=self._device_id,
            value=temp,
        )
