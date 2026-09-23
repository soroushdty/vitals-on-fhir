# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public API for the ``fhir`` package — VitalSign → FHIR resource conversion.

Importing this package registers the default mapper as a load-time side effect:
``ScalarVitalMapper`` is registered for :class:`~vitals_on_fhir.vitals.ScalarVital`
so every scalar vital sign (including :class:`~vitals_on_fhir.vitals.HeartRate`
and future scalar vitals) resolves to it via the MRO through
:func:`resolve_mapper` with no additional mapper code.
"""

from vitals_on_fhir.fhir.base import VitalMapper, register_mapper, resolve_mapper
from vitals_on_fhir.fhir.builders import (
    build_capability_statement,
    build_device,
    build_operation_outcome,
    build_patient,
)
from vitals_on_fhir.fhir.mappers import ComponentVitalMapper, ScalarVitalMapper
from vitals_on_fhir.vitals import ScalarVital

# Register the default scalar mapper as a package-load side effect. Every
# ScalarVital subclass resolves to this instance via resolve_mapper's MRO walk.
register_mapper(ScalarVital, ScalarVitalMapper())

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
