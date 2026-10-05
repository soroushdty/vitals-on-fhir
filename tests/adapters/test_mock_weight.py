# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract suite and emission-mode tests for ``MockWeightAdapter``.

Runs the reusable ``DeviceAdapterContract`` against the mock weight-scale adapter
and verifies each emission mode produces the intended reading so the
plausible-range validator and the Imperial-source path can be exercised without
hardware. The contract suite also statically asserts the mock's defining module
never imports ``bleak`` at module level. ``bleak`` is never imported here.

Requirements: FR-WT-4, FR-WT-8, NFR-WT-6.
"""

from __future__ import annotations

import asyncio

from tests.adapters.contract import DeviceAdapterContract
from vitals_on_fhir.adapters.builtin.mock import (
    MockWeightAdapter,
    WeightEmissionMode,
)
from vitals_on_fhir.vitals import BodyWeight


class TestMockWeightAdapterContract(DeviceAdapterContract):
    """``MockWeightAdapter`` must pass the full ``DeviceAdapter`` contract suite.

    The suite includes the module-level ``bleak``-import AST check (the mock is
    not a hardware adapter), which enforces the never-imports-``bleak``
    guarantee.
    """

    adapter_cls = MockWeightAdapter

    def make_adapter(self) -> MockWeightAdapter:
        """Return a default mock weight adapter instance for the contract checks."""
        return MockWeightAdapter()


async def _first_reading(adapter: MockWeightAdapter) -> BodyWeight:
    """Connect, take one reading, and disconnect."""
    await adapter.connect()
    try:
        async for vital in adapter.vitals():
            assert isinstance(vital, BodyWeight)
            return vital
        raise AssertionError("vitals() ended before yielding a reading")
    finally:
        await adapter.disconnect()


def test_supported_vitals_is_body_weight() -> None:
    """The adapter declares it produces ``BodyWeight`` readings."""
    assert MockWeightAdapter.supported_vitals == (BodyWeight,)


def test_valid_mode_emits_in_range_reading() -> None:
    """The VALID mode emits a weight reading inside the default plausible range."""
    adapter = MockWeightAdapter(WeightEmissionMode.VALID, count=1)
    reading = asyncio.run(_first_reading(adapter))
    assert reading.value == 70.0
    assert reading.effective.tzinfo is not None
    low, high = BodyWeight.plausible_range
    assert low < reading.value < high


def test_implausible_mode_emits_above_upper_bound() -> None:
    """The IMPLAUSIBLE mode emits a weight value above the plausible upper bound."""
    adapter = MockWeightAdapter(WeightEmissionMode.IMPLAUSIBLE, count=1)
    reading = asyncio.run(_first_reading(adapter))
    assert reading.value == 900.0
    _low, high = BodyWeight.plausible_range
    assert reading.value > high


def test_imperial_source_mode_emits_normalized_kilograms() -> None:
    """IMPERIAL_SOURCE emits the already-normalized kilogram equivalent of a pounds source.

    The domain object is always kilograms, mirroring the parser, which normalizes
    pounds to kilograms before constructing the reading.
    """
    adapter = MockWeightAdapter(WeightEmissionMode.IMPERIAL_SOURCE, count=1)
    reading = asyncio.run(_first_reading(adapter))
    assert reading.value == 70.0
    assert reading.effective.tzinfo is not None
    low, high = BodyWeight.plausible_range
    assert low < reading.value < high
