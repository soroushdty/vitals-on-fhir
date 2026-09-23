# SPDX-License-Identifier: AGPL-3.0-or-later
"""Concrete BLE adapter for the standard Bluetooth Blood Pressure Service (GATT 0x1810).

``BloodPressureBleAdapter`` acquires blood-pressure readings from any device
implementing the standard Blood Pressure Service and its Blood Pressure
Measurement characteristic (``0x2A35``). It reuses the shared
:class:`~vitals_on_fhir.adapters.BleConnection` lifecycle *by composition* —
scanning, connecting, subscribing, and reconnecting are implemented once there —
and delegates payload decoding to ``BloodPressureMeasurementParser``.

``bleak`` is imported lazily inside :class:`BleConnection`; it is never imported
at the module level here.

Device and brand names are not referenced: this adapter targets the vendor-
neutral standard profile, so any conforming cuff is supported.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, ClassVar

from vitals_on_fhir.adapters.base import ConnectionState, DeviceAdapter
from vitals_on_fhir.adapters.ble import BleConnection, GattCharacteristicParser
from vitals_on_fhir.vitals.base import DeviceInfo, VitalSign
from vitals_on_fhir.vitals.builtin.blood_pressure import BloodPressure

if TYPE_CHECKING:
    from datetime import datetime

#: GATT UUID of the Blood Pressure Service (0x1810), used to filter advertisements.
BLOOD_PRESSURE_SERVICE_UUID = "00001810-0000-1000-8000-00805f9b34fb"

#: GATT UUID of the Blood Pressure Measurement characteristic (0x2A35).
BLOOD_PRESSURE_MEASUREMENT_UUID = "00002a35-0000-1000-8000-00805f9b34fb"


class BloodPressureBleAdapter(DeviceAdapter):
    """BLE adapter for the standard Bluetooth Blood Pressure Service.

    Composes a :class:`~vitals_on_fhir.adapters.BleConnection` configured for the
    Blood Pressure Service and delegates the connection lifecycle to it. Yields
    ``BloodPressure`` readings decoded by ``BloodPressureMeasurementParser``.
    """

    supported_vitals: ClassVar[tuple[type[VitalSign], ...]] = (BloodPressure,)

    def __init__(
        self,
        *,
        device_name: str | None = None,
        on_state_change: Callable[[ConnectionState], Awaitable[None]] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize the adapter, composing a Blood Pressure Service lifecycle.

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
            service_uuid=BLOOD_PRESSURE_SERVICE_UUID,
            characteristic_uuid=BLOOD_PRESSURE_MEASUREMENT_UUID,
            matches=self.matches,
            parser_factory=self._build_parser,
            device_name=device_name,
            on_state_change=on_state_change,
        )

    def matches(self, advertisement: object) -> bool:
        """Return ``True`` for any standard blood-pressure device advertisement.

        Advertisements reaching this predicate are already pre-filtered by the
        Blood Pressure Service UUID during the scan, which is authoritative for
        selecting a conforming cuff — so every candidate matches. The optional
        ``device_name`` filter (applied by the composed ``BleConnection``)
        remains available (applied by the composed ``BleConnection``) to
        disambiguate when several BP devices are in range.
        """
        return True

    @property
    def device_info(self) -> DeviceInfo:
        """Return vendor-neutral device metadata for a standard BP cuff."""
        return DeviceInfo(
            manufacturer="Generic",
            model="Blood Pressure Monitor",
            identifiers={"profile": "org.bluetooth.service.blood_pressure"},
        )

    @property
    def state(self) -> ConnectionState:
        """Current connection state (managed by the composed lifecycle)."""
        return self._connection.state

    async def connect(self) -> None:
        """Scan for, connect to, and subscribe to a blood-pressure device."""
        await self._connection.connect()

    async def disconnect(self) -> None:
        """Stop notifications, disconnect, and unblock ``vitals()``."""
        await self._connection.disconnect()

    def vitals(self) -> AsyncIterator[VitalSign]:
        """Yield ``BloodPressure`` readings parsed from BLE notifications."""
        return self._connection.vitals()

    def _build_parser(self) -> GattCharacteristicParser:
        """Construct the Blood Pressure Measurement parser for the composed lifecycle.

        Imported lazily to respect the package dependency direction
        (``adapters.bp_parser`` imports ``adapters.ble``, so importing it at
        module load here would risk an import cycle).
        """
        from vitals_on_fhir.adapters.bp_parser import BloodPressureMeasurementParser

        return BloodPressureMeasurementParser(
            device_id=self.device_info.identifiers["profile"],
            now=self._now,
        )
