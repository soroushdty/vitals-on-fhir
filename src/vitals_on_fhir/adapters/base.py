# SPDX-License-Identifier: AGPL-3.0-or-later
"""Device adapter ABC and connection-state enum.

This module defines the abstract interface all device adapters must satisfy,
plus the ``ConnectionState`` enum used to track BLE lifecycle transitions.
It depends only on the Python standard library and the ``vitals`` package.
"""

from __future__ import annotations

import abc
import enum
from collections.abc import AsyncIterator
from typing import ClassVar

from vitals_on_fhir.vitals.base import DeviceInfo, VitalSign


class ConnectionState(enum.Enum):
    """Lifecycle states for a device connection."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


class DeviceAdapter(abc.ABC):
    """Abstract base class for all device adapters.

    An adapter is responsible for establishing a connection to a physical or
    simulated device, maintaining that connection, and yielding ``VitalSign``
    domain objects. No FHIR, validation, or storage logic belongs here.
    """

    supported_vitals: ClassVar[tuple[type[VitalSign], ...]]
    """Vital-sign types this adapter can produce."""

    @property
    @abc.abstractmethod
    def device_info(self) -> DeviceInfo:
        """Immutable description of the connected device."""
        ...

    @property
    @abc.abstractmethod
    def state(self) -> ConnectionState:
        """Current connection state."""
        ...

    @abc.abstractmethod
    async def connect(self) -> None:
        """Establish a connection to the device."""
        ...

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Tear down the connection gracefully."""
        ...

    @abc.abstractmethod
    def vitals(self) -> AsyncIterator[VitalSign]:
        """Yield ``VitalSign`` objects as they arrive from the device.

        This is an async generator that runs indefinitely until the adapter is
        disconnected. Implementations must yield domain objects only — no FHIR
        construction and no validation logic.

        Declared as a regular method returning an ``AsyncIterator`` (rather than
        ``async def``) so that concrete async-generator implementations satisfy
        the type contract; callers still ``async for`` over the result.
        """
        ...
