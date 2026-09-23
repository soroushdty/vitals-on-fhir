# SPDX-License-Identifier: AGPL-3.0-or-later
"""ObservationSink ABC — the output side of the pipeline.

Any component that consumes FHIR Observations produced by the orchestrator
implements this interface.  Concrete examples include the in-memory store and
the dashboard broadcaster.

This module depends only on the Python standard library.  The ``Observation``
type from ``fhir.resources`` is referenced under a ``TYPE_CHECKING`` guard so
that the module can be imported without a hard ``fhir.resources`` dependency
in environments that don't need FHIR output.
"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fhir.resources.R4B.observation import Observation


class ObservationSink(abc.ABC):
    """Abstract base for components that receive published FHIR Observations.

    The pipeline orchestrator fans each generated Observation out to every
    registered sink.  Implementations must not raise on publish errors; they
    should log and continue so that other sinks are unaffected.
    """

    @abc.abstractmethod
    async def publish(self, observation: Observation) -> None:
        """Receive and process a single FHIR Observation.

        Args:
            observation: The ``fhir.resources.observation.Observation`` instance
                produced by the mapper for one validated reading.
        """
        ...
