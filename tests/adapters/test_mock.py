# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract-suite wiring for ``MockAdapter``.

Runs the reusable :class:`~tests.adapters.contract.DeviceAdapterContract` suite
against ``MockAdapter`` so the simulated adapter is verified to satisfy the same
structural contract as any real device adapter (FR-9, FR-13, NFR-6). ``bleak``
is never imported here — this is a non-``hardware`` test.
"""

from __future__ import annotations

import asyncio
import random

import pytest

from tests.adapters.contract import DeviceAdapterContract
from vitals_on_fhir.adapters.builtin.mock import MockAdapter


class TestMockAdapterContract(DeviceAdapterContract):
    """``MockAdapter`` must pass the full ``DeviceAdapter`` contract suite."""

    adapter_cls = MockAdapter

    def make_adapter(self) -> MockAdapter:
        """Return a default ``MockAdapter`` instance for the contract checks."""
        return MockAdapter()


# --- Variable heart rate (hr_range) ----------------------------------------


async def _collect(adapter: MockAdapter) -> list[float]:
    """Connect *adapter* and return the value of every reading it yields."""
    await adapter.connect()
    return [reading.value async for reading in adapter.vitals()]  # type: ignore[attr-defined]


def test_default_mock_emits_fixed_72() -> None:
    """Without ``hr_range`` the mock keeps its legacy constant reading."""
    values = asyncio.run(_collect(MockAdapter(count=20)))

    assert values == [72.0] * 20


def test_hr_range_readings_vary_and_stay_in_range() -> None:
    """With ``hr_range`` readings vary but never leave the configured bounds."""
    adapter = MockAdapter(count=500, hr_range=(40.0, 100.0), rng=random.Random(1))

    values = asyncio.run(_collect(adapter))

    assert len(values) == 500
    assert all(40.0 <= v <= 100.0 for v in values)
    assert len(set(values)) > 10


def test_hr_range_respects_a_narrow_configured_range() -> None:
    """A custom range, even a narrow one, bounds every reading."""
    adapter = MockAdapter(count=300, hr_range=(58.0, 62.0), rng=random.Random(2))

    values = asyncio.run(_collect(adapter))

    assert all(58.0 <= v <= 62.0 for v in values)


def test_hr_range_is_reproducible_with_a_seeded_rng() -> None:
    """The same seed gives the same series."""
    first = asyncio.run(_collect(MockAdapter(count=50, hr_range=(40, 100), rng=random.Random(7))))
    second = asyncio.run(_collect(MockAdapter(count=50, hr_range=(40, 100), rng=random.Random(7))))

    assert first == second


@pytest.mark.parametrize("hr_range", [(100.0, 40.0), (70.0, 70.0)])
def test_invalid_hr_range_is_rejected(hr_range: tuple[float, float]) -> None:
    """``hr_range`` must be ``(low, high)`` with ``low < high``."""
    with pytest.raises(ValueError, match="low < high"):
        MockAdapter(hr_range=hr_range)
