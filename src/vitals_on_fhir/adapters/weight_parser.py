# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parser for the Bluetooth Weight Measurement characteristic (GATT 0x2A9D).

Decodes a Weight Measurement indication into a
:class:`~vitals_on_fhir.vitals.BodyWeight` domain object. The byte-level
decoding — the flags byte, the mandatory uint16 weight field, its unit-dependent
scaling to kilograms, and the optional org.bluetooth date-time field — lives in
pure functions that :class:`WeightMeasurementParser` delegates to, mirroring the
heart-rate, blood-pressure, pulse-oximeter, and temperature parsers.

Unlike those parsers, the weight value is **not** an IEEE-11073 SFLOAT/FLOAT: it
is a plain little-endian uint16 whose physical resolution depends on the flags
byte. In SI mode the raw value is 0.005 kg per unit; in Imperial mode it is
0.01 lb per unit, then converted to kilograms. The two resolutions differ, so
the unit is chosen from the flags byte and never inferred from the value; this
module therefore does not touch :mod:`vitals_on_fhir.adapters.sfloat`. The shared
org.bluetooth date-time decoding is imported from
:mod:`vitals_on_fhir.adapters.datetime_field` (used by the blood-pressure and
temperature parsers too).

Protocol source: Bluetooth SIG Weight Scale Service (``0x181D``) / Weight
Measurement characteristic (``0x2A9D``); see
``docs/protocol-weight-measurement.md``. This slice decodes only the weight
value; the optional user-ID, BMI, and height fields are length-accounted only
and not modelled in the reading, and the user ID is never decoded, logged, or
stored.

Timezone note: the characteristic's optional date-time field carries no
timezone. Per the project's local-home-monitoring assumption, a decoded device
timestamp is interpreted as the host's local time and returned timezone-aware,
matching the blood-pressure convention.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, tzinfo
from typing import NamedTuple

from vitals_on_fhir.adapters.ble import GattCharacteristicParser
from vitals_on_fhir.adapters.datetime_field import TIMESTAMP_SIZE, decode_timestamp
from vitals_on_fhir.vitals.base import VitalSign
from vitals_on_fhir.vitals.builtin.body_weight import BodyWeight

__all__ = [
    "WeightMeasurementParser",
    "WeightFlags",
    "parse_weight_flags",
    "required_length",
    "scale_weight",
]

_logger = logging.getLogger(__name__)

# Weight Measurement flags byte (offset 0) bit positions.
_FLAG_UNIT_IMPERIAL = 0x01  # bit 0: 0 -> SI (kg), 1 -> Imperial (lb)
_FLAG_TIMESTAMP_PRESENT = 0x02  # bit 1: date-time field present (7 bytes)
_FLAG_USER_ID_PRESENT = 0x04  # bit 2: user-ID field present (1 byte)
_FLAG_BMI_HEIGHT_PRESENT = 0x08  # bit 3: BMI + height fields present (2 x uint16 = 4 bytes)

# Field sizes (bytes).
_WEIGHT_SIZE = 2  # mandatory uint16 weight
_USER_ID_SIZE = 1  # optional user-ID (length-accounted only, never decoded)
_BMI_HEIGHT_SIZE = 4  # optional BMI uint16 + height uint16 (length-accounted only)

# Unit-dependent scaling factors (see module docstring / design §2).
_SI_RESOLUTION_KG = 0.005  # kg per raw unit, SI mode
_IMPERIAL_RESOLUTION_LB = 0.01  # lb per raw unit, Imperial mode
_LB_TO_KG = 0.45359237  # exact pound -> kilogram factor

# The mandatory weight uint16 follows the flags byte (offset 1); an optional
# timestamp follows the weight field (offset 1 + weight size).
_WEIGHT_OFFSET = 1
_TIMESTAMP_OFFSET = _WEIGHT_OFFSET + _WEIGHT_SIZE


class WeightFlags(NamedTuple):
    """Decoded view of the Weight Measurement flags byte.

    Internal to this module; not exported from the ``adapters`` package.
    """

    unit_is_imperial: bool
    timestamp_present: bool
    user_id_present: bool
    bmi_height_present: bool


def parse_weight_flags(byte: int) -> WeightFlags:
    """Decode the four relevant bits of the flags byte into a ``WeightFlags`` record."""
    return WeightFlags(
        unit_is_imperial=bool(byte & _FLAG_UNIT_IMPERIAL),
        timestamp_present=bool(byte & _FLAG_TIMESTAMP_PRESENT),
        user_id_present=bool(byte & _FLAG_USER_ID_PRESENT),
        bmi_height_present=bool(byte & _FLAG_BMI_HEIGHT_PRESENT),
    )


def required_length(flags: WeightFlags) -> int:
    """Return the minimum payload length the flags byte declares.

    Accounts for the flags byte, the mandatory uint16 weight, and each optional
    field the flags declare present (timestamp, user ID, BMI + height). The
    user-ID and BMI/height fields are length-accounted only; they are never
    decoded.
    """
    length = 1 + _WEIGHT_SIZE
    if flags.timestamp_present:
        length += TIMESTAMP_SIZE
    if flags.user_id_present:
        length += _USER_ID_SIZE
    if flags.bmi_height_present:
        length += _BMI_HEIGHT_SIZE
    return length


def scale_weight(raw: int, *, imperial: bool) -> float:
    """Scale a raw uint16 Weight Measurement value to kilograms.

    In SI mode the raw value is 0.005 kg per unit. In Imperial mode it is
    0.01 lb per unit, then converted to kilograms. The two resolutions differ;
    the unit is chosen from the flags byte, never inferred from the value. The
    SI/Imperial branch and the pound-to-kilogram conversion are kept in this one
    pure function so a caller cannot split or mis-order them.
    """
    if imperial:
        return raw * _IMPERIAL_RESOLUTION_LB * _LB_TO_KG
    return raw * _SI_RESOLUTION_KG


class WeightMeasurementParser(GattCharacteristicParser):
    """Parses raw GATT 0x2A9D (Weight Measurement) indication payloads.

    Decodes the flags byte and the mandatory uint16 weight (scaled to kilograms
    from SI or Imperial units per the flags), and the optional measurement
    timestamp, returning a ``BodyWeight`` domain object. Returns ``None`` for
    malformed payloads (too short for the fields the flags declare, or a declared
    timestamp that is not a valid calendar date-time) so the adapter can drop them
    silently, logging at ``DEBUG`` with the byte length only, never the value.
    """

    def __init__(
        self,
        device_id: str,
        now: Callable[[], datetime] | None = None,
        tz: tzinfo | None = None,
    ) -> None:
        """Create a parser bound to a device identity and clock.

        Args:
            device_id: Identifier linking parsed readings to a Device resource.
            now: Callable returning a timezone-aware timestamp for the reading's
                ``effective`` time when the payload carries no timestamp.
                Defaults to a local-aware ``datetime.now().astimezone()``.
                Injectable so tests can pin the clock.
            tz: Timezone in which to interpret a device-supplied zoneless
                timestamp. ``None`` (the default) preserves the host-local
                behavior; a non-``None`` value interprets the device wall-clock
                as being in that zone. The ``now`` fallback (no-timestamp path)
                is unaffected.
        """
        self._device_id = device_id
        self._tz = tz
        self._now: Callable[[], datetime] = (
            now if now is not None else (lambda: datetime.now().astimezone())
        )

    @property
    def device_id(self) -> str:
        """Device identifier assigned to readings produced by this parser."""
        return self._device_id

    def parse(self, data: bytes) -> VitalSign | None:
        """Parse a raw Weight Measurement payload.

        Returns a ``BodyWeight`` instance on success, or ``None`` if the payload
        is empty, too short for the fields its flags byte declares, or declares a
        timestamp that is not a valid calendar date-time.
        """
        if len(data) < 1:
            _logger.debug("Dropping empty weight payload (%d bytes)", len(data))
            return None
        flags = parse_weight_flags(data[0])
        if len(data) < required_length(flags):
            _logger.debug("Dropping short weight payload (%d bytes)", len(data))
            return None

        raw = int.from_bytes(
            data[_WEIGHT_OFFSET : _WEIGHT_OFFSET + _WEIGHT_SIZE],
            byteorder="little",
            signed=False,
        )
        value_kg = scale_weight(raw, imperial=flags.unit_is_imperial)

        if flags.timestamp_present:
            effective = decode_timestamp(data, _TIMESTAMP_OFFSET, self._tz)
            if effective is None:
                _logger.debug(
                    "Dropping weight payload with invalid timestamp (%d bytes)",
                    len(data),
                )
                return None
        else:
            effective = self._now()

        return BodyWeight(
            effective=effective,
            device_id=self._device_id,
            value=value_kg,
        )
