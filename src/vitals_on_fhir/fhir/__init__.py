# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public API for the ``fhir`` package — VitalSign → FHIR resource conversion.

Importing this package registers the default mappers as a load-time side effect:
``ScalarVitalMapper`` for :class:`~vitals_on_fhir.vitals.ScalarVital` and
``ComponentVitalMapper`` for :class:`~vitals_on_fhir.vitals.ComponentVital`. Every
scalar vital sign (e.g. :class:`~vitals_on_fhir.vitals.HeartRate`) and every
component vital sign (e.g. :class:`~vitals_on_fhir.vitals.BloodPressure`) resolves
to the appropriate mapper via the MRO through :func:`resolve_mapper` with no
additional mapper code.
"""

from vitals_on_fhir.fhir.base import VitalMapper, register_mapper, resolve_mapper
from vitals_on_fhir.fhir.builders import (
    build_capability_statement,
    build_device,
    build_operation_outcome,
    build_patient,
)
from vitals_on_fhir.fhir.mappers import ComponentVitalMapper, ScalarVitalMapper
from vitals_on_fhir.vitals import ComponentVital, ScalarVital

# Register the default mappers as a package-load side effect. Every ScalarVital
# subclass resolves to ScalarVitalMapper and every ComponentVital subclass to
# ComponentVitalMapper via resolve_mapper's MRO walk, so a new vital-sign type
# needs no mapper code as long as it subclasses one of these bases.
register_mapper(ScalarVital, ScalarVitalMapper())
register_mapper(ComponentVital, ComponentVitalMapper())

__all__ = [
    # ABCs
    "VitalMapper",
    # Concrete defaults
    "ScalarVitalMapper",
    "ComponentVitalMapper",
    "build_device",
    "build_patient",
    "build_capability_statement",
    "build_operation_outcome",
    "register_mapper",
    "resolve_mapper",
]
