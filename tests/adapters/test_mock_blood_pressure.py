# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract suite and emission-mode tests for ``MockBloodPressureAdapter``.

Runs the reusable ``DeviceAdapterContract`` against the mock blood-pressure
adapter and verifies each emission mode produces the intended reading so the
component validator chain and the store-and-forward path can be exercised
without hardware. ``bleak`` is never imported here.

Requirements: FR-HH-9, FR-HH-6, NFR-HH-6.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from tests.adapters.contract import DeviceAdapterContract
from vitals_on_fhir.adapters.builtin.mock import (
    BloodPressureEmissionMode,
    MockBloodPressureAdapter,
)
from vitals_on_fhir.vitals import BloodPressure


class TestMockBloodPressureAdapterContract(DeviceAdapterContract):
    """``MockBloodPressureAdapter`` must pass the full ``DeviceAdapter`` contract suite."""

    adapter_cls = MockBloodPressureAdapter

    def make_adapter(self) -> MockBloodPressureAdapter:
        """Return a default mock BP adapter instance for the contract checks."""
        return MockBloodPressureAdapter()


async def _first_reading(adapter: MockBloodPressureAdapter) -> BloodPressure:
    """Connect, take one reading, and disconnect."""
    await adapter.connect()
    try:
        async for vital in adapter.vitals():
            assert isinstance(vital, BloodPressure)
            return vital
        raise AssertionError("vitals() ended before yielding a reading")
    finally:
        await adapter.disconnect()


def test_valid_mode_emits_in_range_reading() -> None:
    """The VALID mode emits a systolic/diastolic reading inside the default range."""
    adapter = MockBloodPressureAdapter(BloodPressureEmissionMode.VALID, count=1)
    reading = asyncio.run(_first_reading(adapter))
    assert reading.systolic == 118.0
    assert reading.diastolic == 76.0
    assert reading.effective.tzinfo is not None


def test_implausible_systolic_mode() -> None:
    """The IMPLAUSIBLE_SYSTOLIC mode emits an out-of-range systolic."""
    adapter = MockBloodPressureAdapter(
        BloodPressureEmissionMode.IMPLAUSIBLE_SYSTOLIC, count=1
    )
    reading = asyncio.run(_first_reading(adapter))
    assert reading.systolic == 300.0


def test_implausible_diastolic_mode() -> None:
    """The IMPLAUSIBLE_DIASTOLIC mode emits an out-of-range diastolic."""
    adapter = MockBloodPressureAdapter(
        BloodPressureEmissionMode.IMPLAUSIBLE_DIASTOLIC, count=1
    )
    reading = asyncio.run(_first_reading(adapter))
    assert reading.diastolic == 200.0


def test_store_and_forward_mode_has_past_effective_time() -> None:
    """The STORE_AND_FORWARD mode emits a reading whose ``effective`` is in the past."""
    adapter = MockBloodPressureAdapter(
        BloodPressureEmissionMode.STORE_AND_FORWARD, count=1
    )
    reading = asyncio.run(_first_reading(adapter))
    assert reading.effective < datetime.now(UTC)
    # Comfortably in the past (the mode subtracts several minutes).
    assert (datetime.now(UTC) - reading.effective).total_seconds() > 60
