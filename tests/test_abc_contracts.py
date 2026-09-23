# SPDX-License-Identifier: AGPL-3.0-or-later
"""ABC-contract tests: no abstract base class may be instantiated directly.

Every ABC in the project must reject direct instantiation with ``TypeError``.
This enforces the object-model rule that all extension points are abstract and
must be subclassed rather than used directly (FR-13, NFR-6).

ABCs are imported from their packages' public API. Importing ``BleHeartRateAdapter``
must not pull in ``bleak`` — that dependency is imported lazily inside adapter
method bodies only — so this module also asserts ``bleak`` stays unimported.
"""

from __future__ import annotations

import sys

import pytest

from vitals_on_fhir.adapters import (
    BleHeartRateAdapter,
    DeviceAdapter,
    GattCharacteristicParser,
)
from vitals_on_fhir.api import Authenticator
from vitals_on_fhir.fhir import VitalMapper
from vitals_on_fhir.pipeline import ObservationSink
from vitals_on_fhir.store import ObservationStore
from vitals_on_fhir.validation import Validator
from vitals_on_fhir.vitals import ComponentVital, ScalarVital, VitalSign

# Every ABC in the project, imported from its package public API.
ABCS: list[type] = [
    VitalSign,
    ScalarVital,
    ComponentVital,
    DeviceAdapter,
    GattCharacteristicParser,
    BleHeartRateAdapter,
    Validator,
    VitalMapper,
    ObservationSink,
    ObservationStore,
    Authenticator,
]


@pytest.mark.parametrize("abc_cls", ABCS, ids=lambda cls: cls.__name__)
def test_abc_cannot_be_instantiated_directly(abc_cls: type) -> None:
    """Direct instantiation of any ABC raises ``TypeError``."""
    with pytest.raises(TypeError):
        abc_cls()


def test_importing_ble_adapter_does_not_import_bleak() -> None:
    """Importing ``BleHeartRateAdapter`` must not trigger a ``bleak`` import.

    ``bleak`` is a hardware-only dependency imported lazily inside adapter
    method bodies, so mock mode, tests, and CI work without a Bluetooth stack.
    """
    assert "bleak" not in sys.modules
