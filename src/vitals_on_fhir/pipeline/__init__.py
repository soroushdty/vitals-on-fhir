# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public API for the ``pipeline`` package — orchestration from adapter to sinks."""

from vitals_on_fhir.pipeline.base import ObservationSink
from vitals_on_fhir.pipeline.orchestrator import Orchestrator

__all__ = [
    # ABCs
    "ObservationSink",
    # Concrete defaults
    "Orchestrator",
]
