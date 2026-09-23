# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public API for the ``store`` package — Observation persistence and retrieval."""

from vitals_on_fhir.store.base import ObservationStore
from vitals_on_fhir.store.memory import InMemoryObservationStore

__all__ = [
    # ABCs
    "ObservationStore",
    # Concrete defaults
    "InMemoryObservationStore",
]
