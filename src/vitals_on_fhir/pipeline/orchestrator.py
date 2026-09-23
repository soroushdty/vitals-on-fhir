# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pipeline orchestrator — wires adapter → validators → mapper → sinks.

The :class:`Orchestrator` is the composition root of the data pipeline.  It
holds references to all injected collaborators (adapter, validator chain,
mapper, sinks) but contains no concrete business logic itself.  All concrete
implementations are chosen in ``cli.py`` and injected here.

Allowed imports: ``vitals/``, ``adapters/``, ``validation/``, ``fhir/``,
``pipeline/base``, and the Python standard library.  Must NOT import from
``store``, ``api``, ``dashboard``, or ``cli``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from vitals_on_fhir.adapters.base import DeviceAdapter
from vitals_on_fhir.fhir import resolve_mapper
from vitals_on_fhir.fhir.base import VitalMapper
from vitals_on_fhir.pipeline.base import ObservationSink
from vitals_on_fhir.validation.base import ValidatorChain

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from vitals_on_fhir.adapters.base import ConnectionState

logger = logging.getLogger(__name__)


class Orchestrator:
    """Wires a device adapter through validation and FHIR mapping to one or more sinks.

    All collaborators are injected at construction time; the orchestrator
    depends only on ABCs, never on concrete classes.

    Args:
        adapter: The :class:`~vitals_on_fhir.adapters.DeviceAdapter` that
            yields raw :class:`~vitals_on_fhir.vitals.VitalSign` objects.
        validator_chain: A :class:`~vitals_on_fhir.validation.ValidatorChain`
            that accepts or rejects each reading.
        mapper: A :class:`~vitals_on_fhir.fhir.VitalMapper` that converts
            accepted readings to FHIR Observations. Retained for explicit
            injection; per-reading resolution uses :func:`resolve_mapper` so
            each vital-sign type maps via its MRO.
        sinks: Ordered list of :class:`ObservationSink` instances that receive
            each generated Observation.
        patient_ref: FHIR reference string for the subject Patient
            (e.g. ``"Patient/local-patient"``), supplied by ``cli.py``.
        device_ref: FHIR reference string for the source Device
            (e.g. ``"Device/miband10"``), supplied by ``cli.py``.
        state_relay: Optional coroutine invoked with each
            :class:`~vitals_on_fhir.adapters.ConnectionState` change so the
            change can surface to the dashboard. Passed in by ``cli.py`` as a
            plain callable (never a ``dashboard`` reference) to honour the
            dependency-direction rules.
    """

    def __init__(
        self,
        adapter: DeviceAdapter,
        validator_chain: ValidatorChain,
        mapper: VitalMapper,
        sinks: list[ObservationSink],
        *,
        patient_ref: str,
        device_ref: str,
        state_relay: Callable[[ConnectionState], Awaitable[None]] | None = None,
    ) -> None:
        self._adapter = adapter
        self._validator_chain = validator_chain
        self._mapper = mapper
        self._sinks = list(sinks)
        self._patient_ref = patient_ref
        self._device_ref = device_ref
        self._state_relay = state_relay

    async def run(self) -> None:
        """Start the pipeline and run until the adapter is exhausted or disconnected.

        Connects the adapter, then iterates the vital-sign stream. Each reading
        is validated; rejected readings are logged at ``INFO`` (validator name
        and reason, **never the measurement value**) and skipped. Accepted
        readings are mapped to a FHIR Observation via
        :func:`resolve_mapper` and fanned out to every registered sink. A
        failing sink is caught and logged so the remaining sinks still receive
        the Observation.

        Any exception raised while constructing the Observation (e.g. a pydantic
        ``ValidationError``) is caught and logged at ``ERROR`` without the
        measurement value, and the reading is skipped.
        """
        await self._adapter.connect()
        if self._state_relay is not None:
            await self._state_relay(self._adapter.state)

        async for vital in self._adapter.vitals():
            result = self._validator_chain.run(vital)
            if not result.accepted:
                logger.info(
                    "Reading rejected by %s: %s",
                    result.validator_name,
                    result.reason,
                )
                continue

            try:
                mapper = resolve_mapper(type(vital))
                observation = mapper.to_observation(
                    vital,
                    self._patient_ref,
                    self._device_ref,
                    issued=datetime.now(tz=UTC),
                )
            except Exception:
                logger.exception(
                    "Failed to build Observation for a reading from %s; skipping.",
                    type(vital).__name__,
                )
                continue

            for sink in self._sinks:
                try:
                    await sink.publish(observation)
                except Exception:
                    logger.exception(
                        "Sink %s failed to publish an Observation; continuing.",
                        type(sink).__name__,
                    )
