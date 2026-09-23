# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract suite and emission-mode tests for ``MockOximeterAdapter``.

Runs the reusable ``DeviceAdapterContract`` against the mock pulse-oximeter
adapter and verifies each emission mode produces the intended reading so the
plausible-range validator can be exercised without hardware. ``bleak`` is never
imported here.

Requirements: FR-SPO2-8, NFR-SPO2-5, NFR-SPO2-6.
"""

from __future__ import annotations

import asyncio

from tests.adapters.contract import DeviceAdapterContract
from vitals_on_fhir.adapters.builtin.mock import (
    MockOximeterAdapter,
    OximeterEmissionMode,
)
from vitals_on_fhir.vitals import OxygenSaturation


class TestMockOximeterAdapterContract(DeviceAdapterContract):
    """``MockOximeterAdapter`` must pass the full ``DeviceAdapter`` contract suite."""

    adapter_cls = MockOximeterAdapter

    def make_adapter(self) -> MockOximeterAdapter:
        """Return a default mock oximeter adapter instance for the contract checks."""
        return MockOximeterAdapter()


async def _first_reading(adapter: MockOximeterAdapter) -> OxygenSaturation:
    """Connect, take one reading, and disconnect."""
    await adapter.connect()
    try:
        async for vital in adapter.vitals():
            assert isinstance(vital, OxygenSaturation)
            return vital
        raise AssertionError("vitals() ended before yielding a reading")
    finally:
        await adapter.disconnect()


def test_supported_vitals_is_oxygen_saturation() -> None:
    """The adapter declares it produces ``OxygenSaturation`` readings."""
    assert MockOximeterAdapter.supported_vitals == (OxygenSaturation,)


def test_valid_mode_emits_in_range_reading() -> None:
    """The VALID mode emits an SpO2 reading inside the default plausible range."""
    adapter = MockOximeterAdapter(OximeterEmissionMode.VALID, count=1)
    reading = asyncio.run(_first_reading(adapter))
    assert reading.value == 98.0
    assert reading.effective.tzinfo is not None


def test_implausible_mode_emits_below_lower_bound() -> None:
    """The IMPLAUSIBLE mode emits an SpO2 value below the plausible lower bound."""
    adapter = MockOximeterAdapter(OximeterEmissionMode.IMPLAUSIBLE, count=1)
    reading = asyncio.run(_first_reading(adapter))
    assert reading.value == 50.0
    low, _high = OxygenSaturation.plausible_range
    assert reading.value < low
