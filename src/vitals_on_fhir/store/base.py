# SPDX-License-Identifier: AGPL-3.0-or-later
"""ObservationStore ABC — the query side of the observation store.

Any component that persists and retrieves FHIR Observations implements this
interface.  The in-memory implementation in ``memory.py`` is the MVP concrete
class; future specs may add durable backends.

``fhir.resources`` types appear only under a ``TYPE_CHECKING`` guard so that
this module can be imported without a hard dependency on ``fhir.resources``
in environments that don't require FHIR I/O.

Allowed imports: stdlib only (``fhir.resources`` under TYPE_CHECKING).
Must NOT import from ``adapters``, ``validation``, ``api``, ``dashboard``,
or ``cli``.
"""

from __future__ import annotations

import abc
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fhir.resources.R4B.observation import Observation


class ObservationStore(abc.ABC):
    """Abstract base for components that store and retrieve FHIR Observations.

    Implementations must protect shared mutable state with appropriate async
    primitives and return snapshots (copies) from read methods so callers
    cannot mutate internal state.
    """

    @abc.abstractmethod
    async def add(self, observation: Observation) -> None:
        """Persist a single FHIR Observation.

        Args:
            observation: The ``fhir.resources.R4B.observation.Observation`` instance
                to store.
        """
        ...

    @abc.abstractmethod
    async def get(self, observation_id: str) -> Observation | None:
        """Retrieve a single Observation by its logical ID.

        Args:
            observation_id: The ``id`` field of the target Observation.

        Returns:
            The matching ``Observation``, or ``None`` if not found.
        """
        ...

    @abc.abstractmethod
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

        Args:
            code: LOINC code to filter by (e.g. ``"8867-4"``).
            date_from: Inclusive lower bound on ``effectiveDateTime``.
            date_to: Inclusive upper bound on ``effectiveDateTime``.
            sort_desc: If ``True`` (default), return newest first.
            count: Maximum number of results to return.  ``None`` means
                no limit.

        Returns:
            A snapshot list of matching ``Observation`` instances.
        """
        ...
