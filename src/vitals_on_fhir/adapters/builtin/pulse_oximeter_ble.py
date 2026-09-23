# SPDX-License-Identifier: AGPL-3.0-or-later
"""Concrete BLE adapter for the standard Bluetooth Pulse Oximeter Service (GATT 0x1822).

``PulseOximeterBleAdapter`` acquires peripheral oxygen-saturation (SpO2) readings
from any device implementing the standard Pulse Oximeter Service (PLX) and its
PLX Continuous Measurement characteristic (``0x2A5F``). It reuses the shared
:class:`~vitals_on_fhir.adapters.BleConnection` lifecycle *by composition* —
scanning, connecting, subscribing, and reconnecting are implemented once there —
and delegates payload decoding to ``PlxContinuousMeasurementParser``.

``bleak`` is imported lazily inside :class:`BleConnection`; it is never imported
at the module level here.

Device and brand names are not referenced: this adapter targets the vendor-
neutral standard profile, so any conforming pulse oximeter is supported.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, ClassVar

from vitals_on_fhir.adapters.base import ConnectionState, DeviceAdapter
from vitals_on_fhir.adapters.ble import BleConnection, GattCharacteristicParser
from vitals_on_fhir.vitals.base import DeviceInfo, VitalSign
from vitals_on_fhir.vitals.builtin.oxygen_saturation import OxygenSaturation

if TYPE_CHECKING:
    from datetime import datetime

#: GATT UUID of the Pulse Oximeter Service (0x1822), used to filter advertisements.
PULSE_OXIMETER_SERVICE_UUID = "00001822-0000-1000-8000-00805f9b34fb"

#: GATT UUID of the PLX Continuous Measurement characteristic (0x2A5F).
PLX_CONTINUOUS_MEASUREMENT_UUID = "00002a5f-0000-1000-8000-00805f9b34fb"


class PulseOximeterBleAdapter(DeviceAdapter):
    """BLE adapter for the standard Bluetooth Pulse Oximeter Service.

    Composes a :class:`~vitals_on_fhir.adapters.BleConnection` configured for the
    Pulse Oximeter Service and delegates the connection lifecycle to it. Yields
    ``OxygenSaturation`` readings decoded by ``PlxContinuousMeasurementParser``
    from the PLX Continuous Measurement characteristic.
    """

    supported_vitals: ClassVar[tuple[type[VitalSign], ...]] = (OxygenSaturation,)

    def __init__(
        self,
        *,
        device_name: str | None = None,
        on_state_change: Callable[[ConnectionState], Awaitable[None]] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize the adapter, composing a Pulse Oximeter Service lifecycle.

        Args:
            device_name: Optional BLE advertised-name filter (``VOF_DEVICE_NAME``).
                When set, only advertisements whose name matches are considered,
                in addition to the ``matches`` check.
            on_state_change: Optional async callback invoked on every connection
                state transition, wired by ``cli.py`` to relay state to the
                dashboard.
            now: Optional clock returning a timezone-aware timestamp, forwarded
                to the parser (the Continuous Measurement characteristic carries
                no embedded timestamp, so the reading's ``effective`` time is the
                processing time).
        """
        self._now = now
        self._connection = BleConnection(
            service_uuid=PULSE_OXIMETER_SERVICE_UUID,
            characteristic_uuid=PLX_CONTINUOUS_MEASUREMENT_UUID,
            matches=self.matches,
            parser_factory=self._build_parser,
            device_name=device_name,
            on_state_change=on_state_change,
        )

    def matches(self, advertisement: object) -> bool:
        """Return ``True`` for any standard pulse-oximeter advertisement.

        Advertisements reaching this predicate are already pre-filtered by the
        Pulse Oximeter Service UUID during the scan, which is authoritative for
        selecting a conforming device — so every candidate matches. The optional
        ``device_name`` filter (applied by the composed ``BleConnection``)
        remains available to disambiguate when several PLX devices are in range.
        """
        return True

    @property
    def device_info(self) -> DeviceInfo:
        """Return vendor-neutral device metadata for a standard pulse oximeter."""
        return DeviceInfo(
            manufacturer="Generic",
            model="Pulse Oximeter",
            identifiers={"profile": "org.bluetooth.service.pulse_oximeter"},
        )

    @property
    def state(self) -> ConnectionState:
        """Current connection state (managed by the composed lifecycle)."""
        return self._connection.state

    async def connect(self) -> None:
        """Scan for, connect to, and subscribe to a pulse-oximeter device."""
        await self._connection.connect()

    async def disconnect(self) -> None:
        """Stop notifications, disconnect, and unblock ``vitals()``."""
        await self._connection.disconnect()

    def vitals(self) -> AsyncIterator[VitalSign]:
        """Yield ``OxygenSaturation`` readings parsed from BLE notifications."""
        return self._connection.vitals()

    def _build_parser(self) -> GattCharacteristicParser:
        """Construct the PLX Continuous Measurement parser for the composed lifecycle.

        Imported lazily to respect the package dependency direction
        (``adapters.plx_parser`` imports ``adapters.ble``, so importing it at
        module load here would risk an import cycle).
        """
        from vitals_on_fhir.adapters.plx_parser import PlxContinuousMeasurementParser

        return PlxContinuousMeasurementParser(
            device_id=self.device_info.identifiers["profile"],
            now=self._now,
        )
