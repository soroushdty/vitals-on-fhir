# SPDX-License-Identifier: AGPL-3.0-or-later
"""Mock device adapter that produces simulated vital signs without hardware.

``MockAdapter`` never imports ``bleak``. It is used for development, CI, and
tests that don't carry the ``hardware`` marker. Its emission mode lets tests
drive each branch of the validator chain (in-range, out-of-range, and
sensor-contact-lost readings).
"""

from __future__ import annotations

import asyncio
import enum
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import ClassVar

from vitals_on_fhir.adapters.base import ConnectionState, DeviceAdapter
from vitals_on_fhir.vitals.base import DeviceInfo, VitalSign
from vitals_on_fhir.vitals.builtin.heart_rate import HeartRate

_DEFAULT_INTERVAL = 0.01  # seconds between yields; small so tests stay fast
_VALID_HEART_RATE = 72.0  # bpm, comfortably inside the plausible range
_IMPLAUSIBLE_HEART_RATE = 300.0  # bpm, above the default plausible upper bound


class EmissionMode(enum.Enum):
    """Controls the kind of reading ``MockAdapter`` emits.

    - ``VALID`` — in-range readings with sensor contact reported ``True``.
    - ``IMPLAUSIBLE`` — readings whose value is outside the plausible range.
    - ``NO_SENSOR_CONTACT`` — readings with ``sensor_contact`` set to ``False``.
    """

    VALID = "valid"
    IMPLAUSIBLE = "implausible"
    NO_SENSOR_CONTACT = "no_sensor_contact"


class MockAdapter(DeviceAdapter):
    """Simulated device adapter that emits synthetic heart-rate readings.

    Configurable via ``emission_mode`` to produce valid readings, implausible
    values, or readings with lost sensor contact so the full validator chain
    can be exercised in tests. An optional ``count`` bounds how many readings
    are yielded (``None`` yields indefinitely until disconnected), and
    ``interval`` sets the cooperative delay between yields. Never imports
    ``bleak``.
    """

    supported_vitals: ClassVar[tuple[type[VitalSign], ...]] = (HeartRate,)

    def __init__(
        self,
        emission_mode: EmissionMode = EmissionMode.VALID,
        *,
        interval: float = _DEFAULT_INTERVAL,
        count: int | None = None,
    ) -> None:
        """Create a mock adapter.

        Args:
            emission_mode: Which kind of reading to emit; drives the validator
                chain branch under test.
            interval: Seconds to sleep between yielded readings.
            count: Maximum number of readings to yield, or ``None`` to yield
                indefinitely until ``disconnect`` is called.
        """
        self._emission_mode = emission_mode
        self._interval = interval
        self._count = count
        self._state = ConnectionState.DISCONNECTED

    @property
    def device_info(self) -> DeviceInfo:
        """Return a synthetic ``DeviceInfo`` for the mock device."""
        return DeviceInfo(
            manufacturer="vitals-on-fhir",
            model="Mock HR",
            identifiers={"mock": "1"},
        )

    @property
    def state(self) -> ConnectionState:
        """Return the current simulated connection state."""
        return self._state

    async def connect(self) -> None:
        """Simulate connecting to the mock device.

        Transitions ``CONNECTING`` then ``CONNECTED``, consistent with the
        ``DeviceAdapter`` contract.
        """
        self._state = ConnectionState.CONNECTING
        self._state = ConnectionState.CONNECTED

    async def disconnect(self) -> None:
        """Simulate disconnecting from the mock device."""
        self._state = ConnectionState.DISCONNECTED

    async def vitals(self) -> AsyncIterator[VitalSign]:
        """Yield simulated ``HeartRate`` readings per the configured mode.

        Each reading carries a timezone-aware ``effective`` timestamp. Yields
        until ``count`` readings have been produced, or indefinitely while
        connected when ``count`` is ``None``. A small ``asyncio.sleep`` between
        yields keeps the generator cooperative.
        """
        emitted = 0
        while self._state == ConnectionState.CONNECTED:
            if self._count is not None and emitted >= self._count:
                return
            yield self._make_reading()
            emitted += 1
            await asyncio.sleep(self._interval)

    def _make_reading(self) -> HeartRate:
        """Build a single ``HeartRate`` reading for the configured emission mode."""
        effective = datetime.now(UTC)
        if self._emission_mode == EmissionMode.IMPLAUSIBLE:
            return HeartRate(
                effective=effective,
                device_id=self._device_id(),
                value=_IMPLAUSIBLE_HEART_RATE,
                sensor_contact=True,
            )
        if self._emission_mode == EmissionMode.NO_SENSOR_CONTACT:
            return HeartRate(
                effective=effective,
                device_id=self._device_id(),
                value=_VALID_HEART_RATE,
                sensor_contact=False,
            )
        return HeartRate(
            effective=effective,
            device_id=self._device_id(),
            value=_VALID_HEART_RATE,
            sensor_contact=True,
        )

    def _device_id(self) -> str:
        """Return the device identifier used for readings from this adapter."""
        return self.device_info.identifiers["mock"]
