# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hardware-marked integration tests for ``MiBand10Adapter``.

These tests drive a real BLE scan / connect / subscribe against a **physical**
Xiaomi Smart Band 10 with its Heart Rate Service broadcast enabled. They are
the only tests permitted to import ``bleak`` at module level (they carry the
``hardware`` marker, so the fast suite and CI deselect them via the
``-m "not hardware"`` default in ``pyproject.toml``).

Run them explicitly, with a paired device in range and broadcasting::

    uv run pytest -m hardware

Requirements exercised:

- **FR-1** — scan for a device advertising the HRS, connect, maintain one
  connection, and expose ``Connection_State`` through ``state``.
- **FR-2** — subscribe to the HR Measurement characteristic and yield readings
  from ``vitals()`` without user intervention.
- **NFR-2** — detect disconnection and transition to ``RECONNECTING`` /
  recover; verified here indirectly by observing clean state transitions.
- **NFR-6** — the reusable ``DeviceAdapter`` contract suite also applies to the
  real adapter (structural checks; the ``bleak`` module-level check is skipped
  for hardware adapters).

Because these require physical hardware that may not be present, each test is
marked ``hardware`` and additionally skips gracefully when no matching device
is discovered within the scan window, so an accidental invocation on a machine
without the band does not report a hard failure.
"""

from __future__ import annotations

import asyncio

import pytest

from tests.adapters.contract import DeviceAdapterContract
from vitals_on_fhir.adapters.base import ConnectionState
from vitals_on_fhir.adapters.ble import (
    HEART_RATE_SERVICE_UUID,
    BleHeartRateAdapter,
)
from vitals_on_fhir.adapters.builtin.miband10 import MiBand10Adapter
from vitals_on_fhir.vitals.base import VitalSign
from vitals_on_fhir.vitals.builtin.heart_rate import HeartRate

# ``bleak`` is imported lazily inside the test/helper bodies below, never at
# module level. Even though these tests are deselected in the fast suite,
# pytest still *imports* this module during collection; a module-level
# ``import bleak`` would load the Bluetooth stack into ``sys.modules`` and break
# the cross-cutting ``test_importing_ble_adapter_does_not_import_bleak`` check.
# Confining the import to the hardware-marked test bodies keeps ``bleak`` out of
# the fast-suite import graph while still satisfying the rule that ``bleak`` may
# appear only inside hardware-marked modules.
pytestmark = pytest.mark.hardware

#: How long to scan for the band before giving up (seconds).
_SCAN_TIMEOUT = 15.0

#: How long to wait for the first real reading after connecting (seconds).
_READING_TIMEOUT = 20.0


async def _band_is_present() -> bool:
    """Return ``True`` if a Smart Band 10 advertising the HRS is discoverable.

    Performs a bounded scan filtered by the Heart Rate Service UUID and applies
    the adapter's own ``matches`` filter. Used to skip (rather than fail) when
    no physical device is in range.
    """
    import bleak  # lazy: keeps ``bleak`` out of the fast-suite import graph

    adapter = MiBand10Adapter()
    devices = await bleak.BleakScanner.discover(
        timeout=_SCAN_TIMEOUT,
        service_uuids=[HEART_RATE_SERVICE_UUID],
    )
    return any(adapter.matches(device) for device in devices)


def test_miband10_passes_device_adapter_contract() -> None:
    """The real adapter satisfies the reusable ``DeviceAdapter`` contract (NFR-6).

    Structural checks only — no connection is made. The module-level ``bleak``
    import check is skipped for hardware adapters via ``requires_hardware``.
    """

    class _Contract(DeviceAdapterContract):
        adapter_cls = MiBand10Adapter
        requires_hardware = True

        def make_adapter(self) -> MiBand10Adapter:
            return MiBand10Adapter()

    suite = _Contract()
    suite.test_is_concrete_subclass_of_device_adapter()
    suite.test_supported_vitals_is_non_empty_tuple_of_vital_signs()
    suite.test_device_info_returns_device_info()
    suite.test_state_returns_connection_state()
    suite.test_vitals_returns_async_iterator()
    suite.test_no_module_level_bleak_import()


def test_miband10_is_ble_heart_rate_adapter() -> None:
    """``MiBand10Adapter`` is a concrete ``BleHeartRateAdapter`` (FR-1)."""
    assert issubclass(MiBand10Adapter, BleHeartRateAdapter)
    assert MiBand10Adapter.supported_vitals == (HeartRate,)


def test_scan_connect_and_report_connected_state() -> None:
    """Scan for, connect to, and confirm CONNECTED on a real band (FR-1).

    Verifies the full lifecycle transition ``DISCONNECTED`` → ``CONNECTING`` →
    ``CONNECTED`` and that a clean ``disconnect()`` returns to ``DISCONNECTED``.
    State transitions are captured through the injected ``on_state_change``
    callback to confirm they are reported (FR-1, NFR-2).
    """

    async def scenario() -> None:
        if not await _band_is_present():
            pytest.skip("no Xiaomi Smart Band 10 advertising the HRS was found")

        transitions: list[ConnectionState] = []

        async def record(state: ConnectionState) -> None:
            transitions.append(state)

        adapter = MiBand10Adapter(on_state_change=record)
        initial_state: ConnectionState = adapter.state
        assert initial_state == ConnectionState.DISCONNECTED
        try:
            await adapter.connect()
            connected_state: ConnectionState = adapter.state
            assert connected_state == ConnectionState.CONNECTED
            # device_info must report the address discovered during the scan.
            assert adapter.device_info.manufacturer == "Xiaomi"
            assert adapter.device_info.model == "Smart Band 10"
        finally:
            await adapter.disconnect()

        final_state: ConnectionState = adapter.state
        assert final_state == ConnectionState.DISCONNECTED
        assert ConnectionState.CONNECTING in transitions
        assert ConnectionState.CONNECTED in transitions
        assert transitions[-1] == ConnectionState.DISCONNECTED

    asyncio.run(scenario())


def test_subscribe_and_yield_real_reading() -> None:
    """Subscribe to 0x2A37 and yield a real ``HeartRate`` from ``vitals()`` (FR-2).

    Connects, then consumes the first reading the band pushes over the HR
    Measurement characteristic. The reading must be a well-formed ``HeartRate``
    with a plausible value and a timezone-aware ``effective`` timestamp,
    delivered without any user intervention.
    """

    async def scenario() -> None:
        if not await _band_is_present():
            pytest.skip("no Xiaomi Smart Band 10 advertising the HRS was found")

        adapter = MiBand10Adapter()
        reading: VitalSign | None = None
        try:
            await adapter.connect()

            async def first_reading() -> VitalSign:
                async for vital in adapter.vitals():
                    return vital
                raise AssertionError("vitals() ended before yielding a reading")

            reading = await asyncio.wait_for(first_reading(), timeout=_READING_TIMEOUT)
        finally:
            await adapter.disconnect()

        assert isinstance(reading, HeartRate)
        assert reading.effective.tzinfo is not None
        low, high = HeartRate.plausible_range
        assert low <= reading.value <= high

    asyncio.run(scenario())


def test_vitals_generator_stops_on_disconnect() -> None:
    """``vitals()`` terminates cleanly after ``disconnect()`` (FR-2, NFR-2).

    Confirms the generator does not hang after the session ends: once
    ``disconnect()`` pushes its sentinel, iterating ``vitals()`` completes
    rather than blocking indefinitely.
    """

    async def scenario() -> None:
        if not await _band_is_present():
            pytest.skip("no Xiaomi Smart Band 10 advertising the HRS was found")

        adapter = MiBand10Adapter()
        await adapter.connect()
        await adapter.disconnect()

        async def drain() -> int:
            count = 0
            async for _ in adapter.vitals():
                count += 1
            return count

        # Should return promptly (the disconnect sentinel unblocks the queue).
        await asyncio.wait_for(drain(), timeout=5.0)
        assert adapter.state == ConnectionState.DISCONNECTED

    asyncio.run(scenario())
