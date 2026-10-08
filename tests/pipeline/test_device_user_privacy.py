# SPDX-License-Identifier: AGPL-3.0-or-later
"""End-to-end attribution and privacy for multi-user devices (issue #8, ADR-0004).

Real Weight Measurement bytes run through the parser, the validator chain and the
orchestrator. Another user's reading must not be published, and the device user ID
must never appear in any log record or in a published Observation. The measurement
value must not appear in INFO+ logs either.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar

import pytest

from vitals_on_fhir.adapters.base import ConnectionState, DeviceAdapter
from vitals_on_fhir.adapters.weight_parser import WeightMeasurementParser
from vitals_on_fhir.fhir import default_mapper_registry
from vitals_on_fhir.pipeline.base import ObservationSink
from vitals_on_fhir.pipeline.orchestrator import Orchestrator
from vitals_on_fhir.validation import (
    DeviceUserValidator,
    DuplicateValidator,
    PlausibleRangeValidator,
    ValidatorChain,
)
from vitals_on_fhir.vitals import BodyWeight, DeviceInfo, VitalSign

if TYPE_CHECKING:
    from fhir.resources.R4B.observation import Observation

# Distinctive values, so a substring match is a real leak.
_USER_ID = 173
_OTHER_USER_ID = 211
_RAW_WEIGHT = 16384  # x 0.005 kg = 81.92 kg
_VALUE_RENDERINGS = ("81.92",)
_TIMESTAMP = (2026).to_bytes(2, "little") + bytes([10, 6, 8, 30, 0])


def _payload(user_id: int) -> bytes:
    """An SI Weight Measurement with a timestamp and a user ID."""
    return bytes([0x02 | 0x04]) + _RAW_WEIGHT.to_bytes(2, "little") + _TIMESTAMP + bytes([user_id])


class _Sink(ObservationSink):
    def __init__(self) -> None:
        self.published: list[Observation] = []

    async def publish(self, observation: Observation) -> None:
        self.published.append(observation)


class _ScaleAdapter(DeviceAdapter):
    """Parses fixed Weight Measurement payloads with the real parser, no ``bleak``."""

    supported_vitals: ClassVar[tuple[type[VitalSign], ...]] = (BodyWeight,)

    def __init__(self, payload: bytes, configured: int | None) -> None:
        self._payload = payload
        self._parser = WeightMeasurementParser(
            "scale", now=lambda: datetime.now(UTC), device_user_id=configured
        )
        self._state = ConnectionState.DISCONNECTED

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(manufacturer="Generic", model="Weight Scale", identifiers={"x": "scale"})

    @property
    def state(self) -> ConnectionState:
        return self._state

    async def connect(self) -> None:
        self._state = ConnectionState.CONNECTED

    async def disconnect(self) -> None:
        self._state = ConnectionState.DISCONNECTED

    async def vitals(self) -> AsyncIterator[VitalSign]:
        reading = self._parser.parse(self._payload)
        assert reading is not None
        yield reading
        self._state = ConnectionState.DISCONNECTED


def _run(payload: bytes, configured: int | None) -> _Sink:
    sink = _Sink()
    chain = ValidatorChain([PlausibleRangeValidator(), DeviceUserValidator(), DuplicateValidator()])
    orchestrator = Orchestrator(
        _ScaleAdapter(payload, configured),
        chain,
        default_mapper_registry(),
        [sink],
        patient_ref="Patient/local-patient",
        device_ref="Device/scale",
    )
    asyncio.run(orchestrator.run())
    return sink


def _assert_no_leak(records: list[logging.LogRecord], *user_ids: int) -> None:
    for record in records:
        message = record.getMessage()
        for user_id in user_ids:
            assert str(user_id) not in message, f"user ID leaked: {message!r}"
        if record.levelno >= logging.INFO:
            for rendering in _VALUE_RENDERINGS:
                assert rendering not in message, f"value leaked: {message!r}"


@pytest.mark.parametrize(
    ("reported", "configured"),
    [(_OTHER_USER_ID, _USER_ID), (0xFF, _USER_ID), (_USER_ID, None)],
    ids=["another-user", "unknown-user", "not-configured"],
)
def test_reading_not_attributed_to_the_configured_user_is_rejected(
    caplog: pytest.LogCaptureFixture, reported: int, configured: int | None
) -> None:
    """Nothing is published, and the rejection log names neither the user ID nor the value."""
    with caplog.at_level(logging.DEBUG):
        sink = _run(_payload(reported), configured)

    assert sink.published == []
    assert any("device_user" in r.getMessage() for r in caplog.records)
    _assert_no_leak(caplog.records, reported, _USER_ID)


def test_matching_reading_is_published_without_the_user_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The configured user's reading is published, and the user ID is nowhere in it."""
    with caplog.at_level(logging.DEBUG):
        sink = _run(_payload(_USER_ID), _USER_ID)

    assert len(sink.published) == 1
    observation = sink.published[0]
    assert float(observation.valueQuantity.value) == pytest.approx(81.92)
    # ``id`` (a random UUID) and ``issued`` (the wall clock) could contain "173" by chance.
    assert str(_USER_ID) not in observation.model_dump_json(exclude={"id", "issued"})
    _assert_no_leak(caplog.records, _USER_ID)
