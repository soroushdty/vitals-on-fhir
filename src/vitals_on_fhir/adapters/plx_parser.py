# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parser for the Bluetooth PLX Continuous Measurement characteristic (GATT 0x2A5F).

Decodes a PLX Continuous Measurement notification into an
:class:`~vitals_on_fhir.vitals.OxygenSaturation` domain object. The byte-level
decoding — the flags byte and the IEEE-11073 16-bit SFLOAT SpO2 value — lives in
pure functions that :class:`PlxContinuousMeasurementParser` delegates to,
mirroring the heart-rate and blood-pressure parsers. The shared IEEE-11073
SFLOAT decoding is imported from :mod:`vitals_on_fhir.adapters.sfloat` (used by
both this and the blood-pressure parser).

Protocol source: Bluetooth SIG Pulse Oximeter Service / PLX Continuous
Measurement characteristic (see ``docs/protocol-pulse-oximeter-measurement.md``).
The mandatory part is the flags byte followed by the SpO2-PR normal pair (two
consecutive SFLOATs: SpO2 then pulse rate). Only the SpO2 value is decoded into
the reading; the pulse-rate SFLOAT and the optional fields are accounted for in
the required-length calculation but not modelled.

Timezone note: the Continuous Measurement characteristic carries no timestamp,
so a reading's ``effective`` time is the processing time (``now()``), returned
timezone-aware. The clock is injectable for tests.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import NamedTuple

from vitals_on_fhir.adapters.ble import GattCharacteristicParser
from vitals_on_fhir.adapters.sfloat import SFLOAT_SIZE, decode_sfloat
from vitals_on_fhir.vitals.base import VitalSign
from vitals_on_fhir.vitals.builtin.oxygen_saturation import OxygenSaturation

__all__ = [
    "PlxContinuousMeasurementParser",
    "parse_plx_flags",
    "required_length",
]

# PLX Continuous Measurement flags byte (offset 0) bit positions.
_FLAG_SPO2PR_FAST_PRESENT = 0x01  # bit 0: SpO2PR-Fast field present (an extra SFLOAT pair)
_FLAG_SPO2PR_SLOW_PRESENT = 0x02  # bit 1: SpO2PR-Slow field present (an extra SFLOAT pair)
_FLAG_MEASUREMENT_STATUS_PRESENT = 0x04  # bit 2: Measurement Status field present (2 bytes)
_FLAG_DEVICE_SENSOR_STATUS_PRESENT = 0x08  # bit 3: Device and Sensor Status field present (3 bytes)
_FLAG_PULSE_AMPLITUDE_INDEX_PRESENT = 0x10  # bit 4: Pulse Amplitude Index field present (SFLOAT)

# Optional field sizes (bytes).
_SPO2PR_PAIR_SIZE = 2 * SFLOAT_SIZE  # an SpO2 + pulse-rate SFLOAT pair
_MEASUREMENT_STATUS_SIZE = 2
_DEVICE_SENSOR_STATUS_SIZE = 3
_PULSE_AMPLITUDE_INDEX_SIZE = SFLOAT_SIZE

# Mandatory SpO2-PR normal pair follows the flags byte: SpO2 SFLOAT then pulse-rate SFLOAT.
_SPO2_OFFSET = 1
# flags byte (1) + mandatory SpO2 SFLOAT + mandatory pulse-rate SFLOAT.
_MANDATORY_LENGTH = 1 + _SPO2PR_PAIR_SIZE


class PlxFlags(NamedTuple):
    """Decoded view of the PLX Continuous Measurement flags byte.

    Internal to this module; not exported from the ``adapters`` package.
    """

    spo2pr_fast_present: bool
    spo2pr_slow_present: bool
    measurement_status_present: bool
    device_sensor_status_present: bool
    pulse_amplitude_index_present: bool


def parse_plx_flags(byte: int) -> PlxFlags:
    """Decode the five relevant bits of the flags byte into a ``PlxFlags`` record."""
    return PlxFlags(
        spo2pr_fast_present=bool(byte & _FLAG_SPO2PR_FAST_PRESENT),
        spo2pr_slow_present=bool(byte & _FLAG_SPO2PR_SLOW_PRESENT),
        measurement_status_present=bool(byte & _FLAG_MEASUREMENT_STATUS_PRESENT),
        device_sensor_status_present=bool(byte & _FLAG_DEVICE_SENSOR_STATUS_PRESENT),
        pulse_amplitude_index_present=bool(byte & _FLAG_PULSE_AMPLITUDE_INDEX_PRESENT),
    )


def required_length(flags: PlxFlags) -> int:
    """Return the minimum payload length the flags byte declares.

    Accounts for the flags byte, the mandatory SpO2-PR normal SFLOAT pair, and
    each optional field the flags declare present (the fast and slow SFLOAT
    pairs, the measurement-status and device-and-sensor-status fields, and the
    pulse-amplitude-index SFLOAT).
    """
    length = _MANDATORY_LENGTH
    if flags.spo2pr_fast_present:
        length += _SPO2PR_PAIR_SIZE
    if flags.spo2pr_slow_present:
        length += _SPO2PR_PAIR_SIZE
    if flags.measurement_status_present:
        length += _MEASUREMENT_STATUS_SIZE
    if flags.device_sensor_status_present:
        length += _DEVICE_SENSOR_STATUS_SIZE
    if flags.pulse_amplitude_index_present:
        length += _PULSE_AMPLITUDE_INDEX_SIZE
    return length


class PlxContinuousMeasurementParser(GattCharacteristicParser):
    """Parses raw GATT 0x2A5F (PLX Continuous Measurement) notification payloads.

    Decodes the flags byte and the mandatory SpO2 SFLOAT value, returning an
    ``OxygenSaturation`` domain object. The pulse-rate SFLOAT and the optional
    fields are accounted for in the required-length calculation but not decoded
    into the reading. Returns ``None`` for malformed payloads (too short, or a
    reserved/unusable SpO2 SFLOAT) so the adapter can drop them silently.
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
                ``effective`` time. The Continuous Measurement characteristic
                carries no timestamp, so this is always used. Defaults to
                ``datetime.now(UTC)``. Injectable so tests can pin the clock.
        """
        self._device_id = device_id
        self._now: Callable[[], datetime] = now if now is not None else (lambda: datetime.now(UTC))

    @property
    def device_id(self) -> str:
        """Device identifier assigned to readings produced by this parser."""
        return self._device_id

    def parse(self, data: bytes) -> VitalSign | None:
        """Parse a raw PLX Continuous Measurement payload.

        Returns an ``OxygenSaturation`` instance on success, or ``None`` if the
        payload is empty, too short for the fields its flags byte declares, or
        carries a reserved/unusable SpO2 SFLOAT.
        """
        if len(data) < 1:
            return None
        flags = parse_plx_flags(data[0])
        if len(data) < required_length(flags):
            return None
        spo2 = decode_sfloat(data, _SPO2_OFFSET)
        if spo2 is None:
            return None
        return OxygenSaturation(
            effective=self._now(),
            device_id=self._device_id,
            value=spo2,
        )
