# SPDX-License-Identifier: AGPL-3.0-or-later
"""Concrete BLE Heart Rate adapter for the Xiaomi Smart Band 10.

``MiBand10Adapter`` is the reference implementation of ``BleHeartRateAdapter``.
It identifies the device by its advertised name (and the Heart Rate Service it
advertises) and provides the ``DeviceInfo`` for the Xiaomi Smart Band 10. All
BLE scanning, GATT subscription, parsing, and reconnection logic is inherited
from ``BleHeartRateAdapter``; this class adds no scanning or parsing code.

Device and brand names ("Xiaomi", "Smart Band 10") are used only descriptively
to indicate compatibility and do not imply any affiliation or endorsement.
"""

from __future__ import annotations

from typing import Any, ClassVar

from vitals_on_fhir.adapters.ble import BleHeartRateAdapter
from vitals_on_fhir.vitals.base import DeviceInfo, VitalSign
from vitals_on_fhir.vitals.builtin.heart_rate import HeartRate

#: Advertised-name fragments that identify a Xiaomi Smart Band 10. Matched
#: case-insensitively as a substring of the advertisement's ``name`` so minor
#: firmware/locale suffixes (e.g. a trailing identifier) still match.
_ADVERTISED_NAME_FRAGMENTS: tuple[str, ...] = (
    "smart band 10",
    "mi band 10",
    "mi smart band 10",
)


class MiBand10Adapter(BleHeartRateAdapter):
    """BLE Heart Rate Service adapter for the Xiaomi Smart Band 10.

    Implements ``matches`` to filter BLE advertisements by the device's
    advertised name, and provides ``device_info`` with manufacturer and model.
    All BLE scanning, GATT subscription, and reconnection logic is inherited
    from ``BleHeartRateAdapter``.
    """

    supported_vitals: ClassVar[tuple[type[VitalSign], ...]] = (HeartRate,)

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the adapter, deferring lifecycle setup to the base class.

        Args:
            **kwargs: Forwarded to :class:`BleHeartRateAdapter` (``device_name``,
                ``on_state_change``, ``now``).
        """
        super().__init__(**kwargs)
        self._bluetooth_address: str | None = None

    def matches(self, advertisement: object) -> bool:
        """Return ``True`` if the advertisement is from a Xiaomi Smart Band 10.

        The advertisement is a ``bleak`` ``BLEDevice`` at runtime (typed as
        ``object`` here to keep ``bleak`` out of the module-level import graph).
        A device matches when its advertised name contains a known Smart Band 10
        name fragment. Advertisements are already pre-filtered by the Heart Rate
        Service UUID (0x180D) during the base-class scan, so name matching is
        sufficient to select the correct device.

        When a device matches, its Bluetooth address is recorded so
        ``device_info`` can report it as an identifier.
        """
        name = getattr(advertisement, "name", None)
        if not isinstance(name, str):
            return False
        lowered = name.casefold()
        if not any(fragment in lowered for fragment in _ADVERTISED_NAME_FRAGMENTS):
            return False
        address = getattr(advertisement, "address", None)
        if isinstance(address, str):
            self._bluetooth_address = address
        return True

    @property
    def device_info(self) -> DeviceInfo:
        """Return device metadata for the Xiaomi Smart Band 10.

        The ``bluetooth_address`` identifier is populated from the matched
        advertisement's address once :meth:`matches` has selected a device;
        before a device is matched it is reported as ``"unknown"``.
        """
        address = self._bluetooth_address
        return DeviceInfo(
            manufacturer="Xiaomi",
            model="Smart Band 10",
            identifiers={"bluetooth_address": address if address is not None else "unknown"},
        )
