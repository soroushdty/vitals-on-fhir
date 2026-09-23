# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract-suite wiring for ``MockAdapter``.

Runs the reusable :class:`~tests.adapters.contract.DeviceAdapterContract` suite
against ``MockAdapter`` so the simulated adapter is verified to satisfy the same
structural contract as any real device adapter (FR-9, FR-13, NFR-6). ``bleak``
is never imported here — this is a non-``hardware`` test.
"""

from __future__ import annotations

from tests.adapters.contract import DeviceAdapterContract
from vitals_on_fhir.adapters.builtin.mock import MockAdapter


class TestMockAdapterContract(DeviceAdapterContract):
    """``MockAdapter`` must pass the full ``DeviceAdapter`` contract suite."""

    adapter_cls = MockAdapter

    def make_adapter(self) -> MockAdapter:
        """Return a default ``MockAdapter`` instance for the contract checks."""
        return MockAdapter()
