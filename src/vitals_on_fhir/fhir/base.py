# SPDX-License-Identifier: AGPL-3.0-or-later
"""VitalMapper ABC and the mapper registry.

This module depends only on the Python standard library and
``vitals_on_fhir.vitals``. At runtime, ``fhir.resources`` types appear only
under a ``TYPE_CHECKING`` guard so that the module can be imported without a
hard ``fhir.resources`` dependency in environments that don't need FHIR output.
"""

from __future__ import annotations

import abc
from datetime import datetime
from typing import TYPE_CHECKING

from vitals_on_fhir.vitals.base import VitalSign

if TYPE_CHECKING:
    from fhir.resources.R4B.observation import Observation


# ---------------------------------------------------------------------------
# VitalMapper ABC
# ---------------------------------------------------------------------------


class VitalMapper(abc.ABC):
    """Abstract base for classes that convert a :class:`VitalSign` to a FHIR Observation.

    Concrete implementations receive a fully populated :class:`VitalSign` and the
    necessary context references, and return a ``fhir.resources`` ``Observation``
    instance ready for storage or transmission.
    """

    @abc.abstractmethod
    def to_observation(
        self,
        vital: VitalSign,
        patient_ref: str,
        device_ref: str,
        issued: datetime,
    ) -> Observation:
        """Convert *vital* to a FHIR R4 Observation resource.

        Args:
            vital: The :class:`~vitals_on_fhir.vitals.VitalSign` to convert.
            patient_ref: FHIR reference string for the subject Patient
                (e.g. ``"Patient/local-patient"``).
            device_ref: FHIR reference string for the source Device
                (e.g. ``"Device/miband10"``).
            issued: Timezone-aware datetime at which the Observation was
                processed (used for the ``issued`` field; differs from
                ``vital.effective``).

        Returns:
            A ``fhir.resources.R4B.observation.Observation`` instance.
        """
        ...


# ---------------------------------------------------------------------------
# Mapper registry
# ---------------------------------------------------------------------------

_registry: dict[type[VitalSign], VitalMapper] = {}


def register_mapper(vital_class: type[VitalSign], mapper: VitalMapper) -> None:
    """Register *mapper* as the handler for *vital_class* and its subclasses.

    If a mapper is already registered for *vital_class* it is silently
    replaced.  Use :func:`resolve_mapper` to look up a mapper, which walks the
    MRO so subclasses inherit their parent's mapper unless explicitly
    overridden.

    Args:
        vital_class: The :class:`~vitals_on_fhir.vitals.VitalSign` subclass
            this mapper handles.
        mapper: The :class:`VitalMapper` instance to associate with
            *vital_class*.
    """
    _registry[vital_class] = mapper


def resolve_mapper(vital_class: type[VitalSign]) -> VitalMapper:
    """Return the :class:`VitalMapper` registered for *vital_class*.

    Resolution walks the MRO of *vital_class* from most-specific to least,
    returning the first match found.  This means a subclass inherits its
    parent's mapper unless one is explicitly registered for it.

    Args:
        vital_class: The concrete :class:`~vitals_on_fhir.vitals.VitalSign`
            subclass to look up.

    Returns:
        The closest registered :class:`VitalMapper`.

    Raises:
        KeyError: If no mapper is registered for *vital_class* or any of its
            bases.
    """
    for klass in vital_class.__mro__:
        if klass in _registry:
            return _registry[klass]
    raise KeyError(f"No VitalMapper registered for {vital_class.__qualname__} or any of its bases.")
