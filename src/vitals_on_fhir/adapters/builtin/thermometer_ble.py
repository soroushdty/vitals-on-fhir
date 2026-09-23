# SPDX-License-Identifier: AGPL-3.0-or-later
"""Concrete BLE adapter for the standard Bluetooth Health Thermometer Service (GATT 0x1809).

``HealthThermometerBleAdapter`` acquires body-temperature readings from any
device implementing the standard Health Thermometer Service (HTS) and its
Temperature Measurement characteristic (``0x2A1C``). It reuses the shared
:class:`~vitals_on_fhir.adapters.BleConnection` lifecycle *by composition* —
scanning, connecting, subscribing (``bleak`` handles the characteristic's
indications transparently), and reconnecting are implemented once there — and
delegates payload decoding to ``TemperatureMeasurementParser``.

``bleak`` is imported lazily inside :class:`BleConnection`; it is never imported
at the module level here.

Device and brand names are not referenced: this adapter targets the vendor-
neutral standard profile, so any conforming thermometer is supported.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, ClassVar

from vitals_on_fhir.adapters.base import ConnectionState, DeviceAdapter
from vitals_on_fhir.adapters.ble import BleConnection, GattCharacteristicParser
from vitals_on_fhir.vitals.base import DeviceInfo, VitalSign
from vitals_on_fhir.vitals.builtin.body_temperature import BodyTemperature

if TYPE_CHECKING:
    from datetime import datetime

#: GATT UUID of the Health Thermometer Service (0x1809), used to filter advertisements.
HEALTH_THERMOMETER_SERVICE_UUID = "00001809-0000-1000-8000-00805f9b34fb"

#: GATT UUID of the Temperature Measurement characteristic (0x2A1C).
TEMPERATURE_MEASUREMENT_UUID = "00002a1c-0000-1000-8000-00805f9b34fb"


class HealthThermometerBleAdapter(DeviceAdapter):
    """BLE adapter for the standard Bluetooth Health Thermometer Service.

    Composes a :class:`~vitals_on_fhir.adapters.BleConnection` configured for the
    Health Thermometer Service and delegates the connection lifecycle to it.
    Yields ``BodyTemperature`` readings decoded by
    ``TemperatureMeasurementParser`` from the Temperature Measurement
    characteristic.
    """

    supported_vitals: ClassVar[tuple[type[VitalSign], ...]] = (BodyTemperature,)

    def __init__(
        self,
        *,
        device_name: str | None = None,
        on_state_change: Callable[[ConnectionState], Awaitable[None]] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize the adapter, composing a Health Thermometer Service lifecycle.

        Args:
            device_name: Optional BLE advertised-name filter (``VOF_DEVICE_NAME``).
                When set, only advertisements whose name matches are considered,
                in addition to the ``matches`` check.
            on_state_change: Optional async callback invoked on every connection
                state transition, wired by ``cli.py`` to relay state to the
                dashboard.
            now: Optional clock returning a timezone-aware timestamp, forwarded
                to the parser for readings that carry no embedded timestamp.
        """
        self._now = now
        self._connection = BleConnection(
            service_uuid=HEALTH_THERMOMETER_SERVICE_UUID,
            characteristic_uuid=TEMPERATURE_MEASUREMENT_UUID,
            matches=self.matches,
            parser_factory=self._build_parser,
            device_name=device_name,
            on_state_change=on_state_change,
        )

    def matches(self, advertisement: object) -> bool:
        """Return ``True`` for any standard health-thermometer advertisement.

        Advertisements reaching this predicate are already pre-filtered by the
        Health Thermometer Service UUID during the scan, which is authoritative
        for selecting a conforming device — so every candidate matches. The
        optional ``device_name`` filter (applied by the composed
        ``BleConnection``) remains available to disambiguate when several
        thermometers are in range.
        """
        return True

    @property
    def device_info(self) -> DeviceInfo:
        """Return vendor-neutral device metadata for a standard thermometer."""
        return DeviceInfo(
            manufacturer="Generic",
            model="Thermometer",
            identifiers={"profile": "org.bluetooth.service.health_thermometer"},
        )

    @property
    def state(self) -> ConnectionState:
        """Current connection state (managed by the composed lifecycle)."""
        return self._connection.state

    async def connect(self) -> None:
        """Scan for, connect to, and subscribe to a health-thermometer device."""
        await self._connection.connect()

    async def disconnect(self) -> None:
        """Stop notifications, disconnect, and unblock ``vitals()``."""
        await self._connection.disconnect()

    def vitals(self) -> AsyncIterator[VitalSign]:
        """Yield ``BodyTemperature`` readings parsed from BLE notifications."""
        return self._connection.vitals()

    def _build_parser(self) -> GattCharacteristicParser:
        """Construct the Temperature Measurement parser for the composed lifecycle.

        Imported lazily to respect the package dependency direction
        (``adapters.temp_parser`` imports ``adapters.ble``, so importing it at
        module load here would risk an import cycle).
        """
        from vitals_on_fhir.adapters.temp_parser import TemperatureMeasurementParser

        return TemperatureMeasurementParser(
            device_id=self.device_info.identifiers["profile"],
            now=self._now,
        )
