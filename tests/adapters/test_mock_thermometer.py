# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract suite and emission-mode tests for ``MockThermometerAdapter``.

Runs the reusable ``DeviceAdapterContract`` against the mock health-thermometer
adapter and verifies each emission mode produces the intended reading so the
plausible-range validator and the Fahrenheit-source path can be exercised
without hardware. The contract suite also statically asserts the mock's defining
module never imports ``bleak`` at module level. ``bleak`` is never imported here.

Requirements: FR-TEMP-4, FR-TEMP-8, NFR-TEMP-6.
"""

from __future__ import annotations

import asyncio

from tests.adapters.contract import DeviceAdapterContract
from vitals_on_fhir.adapters.builtin.mock import (
    MockThermometerAdapter,
    ThermometerEmissionMode,
)
from vitals_on_fhir.vitals import BodyTemperature


class TestMockThermometerAdapterContract(DeviceAdapterContract):
    """``MockThermometerAdapter`` must pass the full ``DeviceAdapter`` contract suite.

    The suite includes the module-level ``bleak``-import AST check (the mock is
    not a hardware adapter), which enforces the never-imports-``bleak``
    guarantee.
    """

    adapter_cls = MockThermometerAdapter

    def make_adapter(self) -> MockThermometerAdapter:
        """Return a default mock thermometer adapter instance for the contract checks."""
        return MockThermometerAdapter()


async def _first_reading(adapter: MockThermometerAdapter) -> BodyTemperature:
    """Connect, take one reading, and disconnect."""
    await adapter.connect()
    try:
        async for vital in adapter.vitals():
            assert isinstance(vital, BodyTemperature)
            return vital
        raise AssertionError("vitals() ended before yielding a reading")
    finally:
        await adapter.disconnect()


def test_supported_vitals_is_body_temperature() -> None:
    """The adapter declares it produces ``BodyTemperature`` readings."""
    assert MockThermometerAdapter.supported_vitals == (BodyTemperature,)


def test_valid_mode_emits_in_range_reading() -> None:
    """The VALID mode emits a temperature reading inside the default plausible range."""
    adapter = MockThermometerAdapter(ThermometerEmissionMode.VALID, count=1)
    reading = asyncio.run(_first_reading(adapter))
    assert reading.value == 37.0
    assert reading.effective.tzinfo is not None
    low, high = BodyTemperature.plausible_range
    assert low < reading.value < high


def test_implausible_mode_emits_below_lower_bound() -> None:
    """The IMPLAUSIBLE mode emits a temperature value below the plausible lower bound."""
    adapter = MockThermometerAdapter(ThermometerEmissionMode.IMPLAUSIBLE, count=1)
    reading = asyncio.run(_first_reading(adapter))
    assert reading.value == 5.0
    low, _high = BodyTemperature.plausible_range
    assert reading.value < low


def test_fahrenheit_source_mode_emits_normalized_celsius() -> None:
    """FAHRENHEIT_SOURCE emits the already-normalized Celsius equivalent (98.6 F -> 37.0 C).

    The domain object is always Celsius, mirroring the parser, which normalizes
    Fahrenheit to Celsius before constructing the reading.
    """
    adapter = MockThermometerAdapter(ThermometerEmissionMode.FAHRENHEIT_SOURCE, count=1)
    reading = asyncio.run(_first_reading(adapter))
    assert reading.value == 37.0
    assert reading.effective.tzinfo is not None
    low, high = BodyTemperature.plausible_range
    assert low < reading.value < high
