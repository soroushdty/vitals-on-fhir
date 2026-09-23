# SPDX-License-Identifier: AGPL-3.0-or-later
"""InMemoryObservationStore — bounded, lock-protected in-memory store.

This module provides the MVP concrete implementation of both
:class:`~vitals_on_fhir.store.ObservationStore` and
:class:`~vitals_on_fhir.pipeline.ObservationSink`.  Observations are kept in
memory only; they are lost on process restart.

The store is bounded by ``VOF_STORE_MAX`` (default 10 000).  When the bound is
reached the oldest entry is evicted before the new one is inserted.  All
mutations and reads are protected by an :class:`asyncio.Lock`; reads return
deep copies so callers cannot mutate internal state.

Allowed imports: stdlib, ``pipeline/`` (for ``ObservationSink``), and
``fhir.resources`` (under TYPE_CHECKING for type hints).
Must NOT import from ``adapters``, ``validation``, ``api``, ``dashboard``,
or ``cli``.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from vitals_on_fhir.pipeline.base import ObservationSink
from vitals_on_fhir.store.base import ObservationStore

if TYPE_CHECKING:
    from fhir.resources.R4B.observation import Observation


class InMemoryObservationStore(ObservationStore, ObservationSink):
    """Bounded, asyncio-safe in-memory store for FHIR Observations.

    Implements both :class:`~vitals_on_fhir.store.ObservationStore` (query
    interface) and :class:`~vitals_on_fhir.pipeline.ObservationSink` (push
    interface) so it can be registered with the orchestrator as a sink and
    queried by the API layer as a store.

    Observations are held in an :class:`~collections.OrderedDict` keyed by the
    Observation ``id``, giving O(1) lookup by id and ordered oldest-first
    eviction via ``popitem(last=False)``.  The store starts empty on every
    process launch; there is no persistence.

    Args:
        max_size: Maximum number of Observations to retain.  Oldest entries
            are evicted when the limit is reached.  Defaults to ``10_000``.
    """

    def __init__(self, max_size: int = 10_000) -> None:
        self._max_size = max_size
        self._items: OrderedDict[str, Observation] = OrderedDict()
        self._lock = asyncio.Lock()

    @staticmethod
    def _copy(observation: Observation) -> Observation:
        """Return a deep copy of *observation* so callers get an isolated snapshot."""
        return observation.model_copy(deep=True)

    # ------------------------------------------------------------------
    # ObservationSink
    # ------------------------------------------------------------------

    async def publish(self, observation: Observation) -> None:
        """Receive an Observation from the pipeline and persist it.

        Delegates to :meth:`add`.

        Args:
            observation: The FHIR Observation to store.
        """
        await self.add(observation)

    # ------------------------------------------------------------------
    # ObservationStore
    # ------------------------------------------------------------------

    async def add(self, observation: Observation) -> None:
        """Add *observation* to the store, evicting the oldest if at capacity.

        The bound is never exceeded: when the store already holds ``max_size``
        entries the oldest is removed (``popitem(last=False)``) before the new
        entry is inserted.  A store with ``max_size <= 0`` retains nothing.

        Args:
            observation: The FHIR Observation to persist.
        """
        observation_id = str(observation.id)
        async with self._lock:
            # Re-inserting an existing id must not grow the store; drop the old
            # entry first so ordering reflects the latest insertion.
            self._items.pop(observation_id, None)
            if self._max_size <= 0:
                return
            while len(self._items) >= self._max_size:
                self._items.popitem(last=False)
            self._items[observation_id] = self._copy(observation)

    async def get(self, observation_id: str) -> Observation | None:
        """Return the Observation with the given ID, or ``None`` if absent.

        Args:
            observation_id: Logical ID of the target Observation.

        Returns:
            A deep-copied Observation snapshot, or ``None``.  Never a live
            reference to internal state.
        """
        async with self._lock:
            observation = self._items.get(observation_id)
            if observation is None:
                return None
            return self._copy(observation)

    async def search(
        self,
        *,
        code: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        sort_desc: bool = True,
        count: int | None = None,
    ) -> list[Observation]:
        """Search stored Observations with optional filters.

        Filters by LOINC ``code`` (matched against ``code.coding[0].code``) and
        by ``effectiveDateTime`` range (inclusive bounds), sorts by
        ``effectiveDateTime`` (newest first when ``sort_desc``), and truncates
        to ``count`` results.  Every returned Observation is a deep-copied
        snapshot.

        Args:
            code: LOINC code filter.
            date_from: Inclusive lower bound on ``effectiveDateTime``.
            date_to: Inclusive upper bound on ``effectiveDateTime``.
            sort_desc: Return newest first when ``True`` (default).
            count: Maximum results; ``None`` means no limit.

        Returns:
            A snapshot list of matching Observations.
        """
        async with self._lock:
            snapshot = list(self._items.values())

        matches = [
            observation
            for observation in snapshot
            if self._matches(observation, code, date_from, date_to)
        ]
        matches.sort(key=self._effective_sort_key, reverse=sort_desc)

        if count is not None:
            matches = matches[:count]

        return [self._copy(observation) for observation in matches]

    # ------------------------------------------------------------------
    # Internal filter/sort helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _loinc_code(observation: Observation) -> str | None:
        """Return the first LOINC coding ``code`` of *observation*, if any."""
        observation_code = observation.code
        if observation_code is None:
            return None
        coding = observation_code.coding
        if not coding:
            return None
        return coding[0].code

    @staticmethod
    def _effective(observation: Observation) -> datetime | None:
        """Return the ``effectiveDateTime`` of *observation*, if present."""
        return getattr(observation, "effectiveDateTime", None)

    @classmethod
    def _effective_sort_key(cls, observation: Observation) -> datetime:
        """Sort key for ordering by ``effectiveDateTime``.

        Observations without an ``effectiveDateTime`` sort as the earliest by
        using ``datetime.min`` (timezone-aware to stay comparable).
        """
        effective = cls._effective(observation)
        if effective is None:
            return datetime.min.replace(tzinfo=UTC)
        if effective.tzinfo is None:
            return effective.replace(tzinfo=UTC)
        return effective

    @classmethod
    def _matches(
        cls,
        observation: Observation,
        code: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> bool:
        """Return ``True`` if *observation* passes the code and date filters."""
        if code is not None and cls._loinc_code(observation) != code:
            return False

        if date_from is not None or date_to is not None:
            effective = cls._effective(observation)
            if effective is None:
                return False
            if date_from is not None and effective < date_from:
                return False
            if date_to is not None and effective > date_to:
                return False

        return True
