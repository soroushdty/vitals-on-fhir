# SPDX-License-Identifier: AGPL-3.0-or-later
"""Patient-generated and simulated-data markers (ADR-0002, issue #6).

Every Observation carries the PHD category next to vital-signs and names the
Patient as ``performer``; Observations and Devices from a simulated device carry
the ``HTEST`` security label, and real ones never do.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from vitals_on_fhir.adapters import (
    BloodPressureBleAdapter,
    HealthThermometerBleAdapter,
    MiBand10Adapter,
    MockAdapter,
    MockBloodPressureAdapter,
    MockOximeterAdapter,
    MockThermometerAdapter,
    MockWeightAdapter,
    PulseOximeterBleAdapter,
    WeightScaleBleAdapter,
)
from vitals_on_fhir.fhir import (
    ComponentVitalMapper,
    ScalarVitalMapper,
    build_device,
    mark_simulated,
)
from vitals_on_fhir.fhir.provenance import HTEST_SECURITY_LABEL, PHD_CATEGORY
from vitals_on_fhir.vitals import BloodPressure, HeartRate
from vitals_on_fhir.vitals.base import DeviceInfo

if TYPE_CHECKING:
    from fhir.resources.R4B.observation import Observation

    from vitals_on_fhir.adapters import DeviceAdapter

_PATIENT_REF = "Patient/local-patient"
_DEVICE_REF = "Device/some-device"
_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _heart_rate_observation() -> Observation:
    reading = HeartRate(effective=_WHEN, device_id="dev-1", value=72.0)
    return ScalarVitalMapper().to_observation(reading, _PATIENT_REF, _DEVICE_REF, _WHEN)


def _blood_pressure_observation() -> Observation:
    reading = BloodPressure(effective=_WHEN, device_id="cuff-1", systolic=118.0, diastolic=76.0)
    return ComponentVitalMapper().to_observation(reading, _PATIENT_REF, _DEVICE_REF, _WHEN)


def _category_codes(observation: Observation) -> list[tuple[str, str]]:
    return [
        (str(coding.system), str(coding.code))
        for category in observation.category
        for coding in category.coding
    ]


def _security_codes(resource: object) -> list[tuple[str, str]]:
    meta = getattr(resource, "meta", None)
    labels = (meta.security or []) if meta is not None else []
    return [(str(label.system), str(label.code)) for label in labels]


_PHD = (PHD_CATEGORY["coding"][0]["system"], PHD_CATEGORY["coding"][0]["code"])  # type: ignore[index]
_HTEST = (HTEST_SECURITY_LABEL["system"], HTEST_SECURITY_LABEL["code"])


@pytest.mark.parametrize("build", [_heart_rate_observation, _blood_pressure_observation])
def test_every_observation_is_marked_patient_generated(build: object) -> None:
    """Both mappers add the PHD category after vital-signs and the Patient as performer."""
    observation = build()  # type: ignore[operator]

    assert _category_codes(observation) == [
        ("http://terminology.hl7.org/CodeSystem/observation-category", "vital-signs"),
        ("http://hl7.org/fhir/uv/phd/CodeSystem/PhdObservationCategories", "phd"),
    ]
    assert [p.reference for p in observation.performer] == [_PATIENT_REF]
    # The mapper alone never labels data as simulated; the orchestrator does.
    assert _security_codes(observation) == []


def test_mark_simulated_adds_htest_once_and_keeps_everything_else() -> None:
    """``mark_simulated`` adds HTEST, is idempotent, and changes nothing else."""
    original = _heart_rate_observation()

    marked = mark_simulated(original)
    twice = mark_simulated(marked)

    assert _security_codes(marked) == [_HTEST]
    assert _security_codes(twice) == [_HTEST]
    assert _security_codes(original) == []  # the input is not mutated
    stripped = marked.model_dump(mode="json")
    del stripped["meta"]["security"]
    assert stripped == original.model_dump(mode="json")


def test_simulated_device_is_labelled_and_real_device_is_not() -> None:
    """``build_device`` labels only a simulated device as test data."""
    real = DeviceInfo(manufacturer="Acme", model="Cuff", identifiers={})
    simulated = DeviceInfo(manufacturer="Acme", model="Cuff", identifiers={}, simulated=True)

    assert _security_codes(build_device(real)) == []
    assert _security_codes(build_device(simulated)) == [_HTEST]


@pytest.mark.parametrize(
    "adapter",
    [
        MockAdapter(),
        MockBloodPressureAdapter(),
        MockOximeterAdapter(),
        MockThermometerAdapter(),
        MockWeightAdapter(),
    ],
)
def test_every_mock_adapter_reports_a_simulated_device(adapter: DeviceAdapter) -> None:
    """All five mock adapters declare their device simulated."""
    assert adapter.device_info.simulated is True


@pytest.mark.parametrize(
    "adapter_class",
    [
        MiBand10Adapter,
        BloodPressureBleAdapter,
        PulseOximeterBleAdapter,
        HealthThermometerBleAdapter,
        WeightScaleBleAdapter,
    ],
)
def test_real_device_adapters_are_not_simulated(adapter_class: type[DeviceAdapter]) -> None:
    """The built-in BLE adapters describe real devices."""
    assert adapter_class().device_info.simulated is False
