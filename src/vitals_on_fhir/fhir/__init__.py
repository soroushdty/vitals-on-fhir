# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public API for the ``fhir`` package — VitalSign → FHIR resource conversion.

:func:`default_mapper_registry` builds the registry the composition root injects
into the orchestrator: ``ScalarVitalMapper`` for
:class:`~vitals_on_fhir.vitals.ScalarVital` and ``ComponentVitalMapper`` for
:class:`~vitals_on_fhir.vitals.ComponentVital`. Every scalar vital sign (e.g.
:class:`~vitals_on_fhir.vitals.HeartRate`) and every component vital sign (e.g.
:class:`~vitals_on_fhir.vitals.BloodPressure`) resolves to the appropriate mapper
via the MRO with no additional mapper code. Importing this package registers
nothing.
"""

from vitals_on_fhir.fhir.base import MapperRegistry, VitalMapper
from vitals_on_fhir.fhir.builders import (
    build_capability_statement,
    build_device,
    build_operation_outcome,
    build_patient,
)
from vitals_on_fhir.fhir.mappers import ComponentVitalMapper, ScalarVitalMapper
from vitals_on_fhir.fhir.provenance import mark_simulated
from vitals_on_fhir.vitals import ComponentVital, ScalarVital


def default_mapper_registry() -> MapperRegistry:
    """Return a new registry with the default mappers.

    Every ``ScalarVital`` subclass resolves to ``ScalarVitalMapper`` and every
    ``ComponentVital`` subclass to ``ComponentVitalMapper`` via the MRO walk, so
    a new vital-sign type needs no mapper code as long as it subclasses one of
    these bases.

    Returns:
        A :class:`MapperRegistry` the caller owns and may extend.
    """
    registry = MapperRegistry()
    registry.register(ScalarVital, ScalarVitalMapper())
    registry.register(ComponentVital, ComponentVitalMapper())
    return registry


__all__ = [
    # ABCs
    "VitalMapper",
    # Mapper registry
    "MapperRegistry",
    "default_mapper_registry",
    # Concrete defaults
    "ScalarVitalMapper",
    "ComponentVitalMapper",
    "build_device",
    "build_patient",
    "build_capability_statement",
    "build_operation_outcome",
    "mark_simulated",
]
