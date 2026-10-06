# SPDX-License-Identifier: AGPL-3.0-or-later
"""Domain model ABCs and value objects for vital signs.

This module is the root of the vitals hierarchy. It depends only on the Python
standard library — no other vitals_on_fhir packages are imported here.
"""

from __future__ import annotations

import abc
import enum
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar


class DeviceIssue(enum.Enum):
    """A problem the device itself reports about a reading (ADR-0005).

    Parsers translate a device's status bits into these members, keeping only the
    bits that say the value cannot be trusted or is not final. The values are the
    human-readable names used in rejection reasons. Bit sources are documented in
    the ``docs/protocol-*.md`` files.
    """

    # Blood pressure (Measurement Status)
    BODY_MOVEMENT = "body movement"
    CUFF_TOO_LOOSE = "cuff too loose"
    IMPROPER_POSITION = "improper measurement position"

    # Pulse oximetry (Measurement Status)
    MEASUREMENT_ONGOING = "measurement ongoing"
    EARLY_ESTIMATE = "early estimated data"
    DATA_FROM_STORAGE = "data from measurement storage"
    DEMONSTRATION_DATA = "data for demonstration"
    TEST_DATA = "data for testing"
    CALIBRATION_ONGOING = "calibration ongoing"
    MEASUREMENT_UNAVAILABLE = "measurement unavailable"
    QUESTIONABLE_MEASUREMENT = "questionable measurement"
    INVALID_MEASUREMENT = "invalid measurement"

    # Pulse oximetry (Device and Sensor Status)
    EQUIPMENT_MALFUNCTION = "equipment malfunction"
    SIGNAL_PROCESSING_IRREGULARITY = "signal processing irregularity"
    INADEQUATE_SIGNAL = "inadequate signal"
    POOR_SIGNAL = "poor signal"
    LOW_PERFUSION = "low perfusion"
    ERRATIC_SIGNAL = "erratic signal"
    NON_PULSATILE_SIGNAL = "non-pulsatile signal"
    QUESTIONABLE_PULSE = "questionable pulse"
    SIGNAL_ANALYSIS_ONGOING = "signal analysis ongoing"
    SENSOR_INTERFERENCE = "sensor interference"
    SENSOR_UNCONNECTED = "sensor unconnected to user"
    UNKNOWN_SENSOR = "unknown sensor connected"
    SENSOR_DISPLACED = "sensor displaced"
    SENSOR_MALFUNCTIONING = "sensor malfunctioning"
    SENSOR_DISCONNECTED = "sensor disconnected"


@dataclass(frozen=True, kw_only=True)
class VitalSign(abc.ABC):
    """Abstract base for all vital-sign domain objects.

    Subclasses must declare ``loinc_code`` and ``us_core_profile`` as class
    variables. An attempt to instantiate a concrete subclass that omits either
    raises ``TypeError`` at import time (enforced by ``__init_subclass__``).
    """

    effective: datetime
    """Timezone-aware timestamp of when the measurement was taken."""

    device_id: str
    """Identifier linking this reading to a Device resource."""

    device_issues: frozenset[DeviceIssue] = frozenset()
    """Problems the device reported about this reading; empty when none (or not reported).

    ``DeviceStatusValidator`` rejects a reading with any issue (ADR-0005).
    """

    loinc_code: ClassVar[str]
    """LOINC code for the vital-sign concept (e.g. ``"8867-4"`` for heart rate)."""

    us_core_profile: ClassVar[str]
    """Canonical URL of the US Core profile this vital sign conforms to."""

    additional_loinc_codes: ClassVar[tuple[str, ...]] = ()
    """Further LOINC codes the profile requires next to ``loinc_code``.

    Empty for most vitals. US Core Pulse Oximetry, for example, requires ``"2708-6"``
    alongside ``"59408-5"``. Mappers emit these codings after ``loinc_code``, which
    stays the first coding.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Only enforce the ClassVar contract on classes that actually assign a value
        # to ``loinc_code`` (i.e. concrete leaf classes).  Abstract intermediaries
        # like ``ScalarVital`` and ``ComponentVital`` intentionally leave these as
        # unassigned ClassVar annotations, so we skip them.
        if "loinc_code" in cls.__dict__:
            _check_class_vars(cls)


def _check_class_vars(cls: type) -> None:
    """Raise ``TypeError`` if a concrete ``VitalSign`` subclass is missing required metadata."""
    missing = [
        attr
        for attr in ("loinc_code", "us_core_profile")
        if not any(attr in c.__dict__ for c in cls.__mro__ if c is not VitalSign)
    ]
    if missing:
        raise TypeError(f"{cls.__qualname__} must define ClassVar(s): {', '.join(missing)}")


@dataclass(frozen=True, kw_only=True)
class ScalarVital(VitalSign):
    """Abstract base for vital signs represented as a single numeric value."""

    value: float
    """The measured numeric value in the units given by ``ucum_unit``."""

    ucum_unit: ClassVar[str]
    """UCUM unit string (e.g. ``"/min"`` for beats-per-minute)."""

    plausible_range: ClassVar[tuple[float, float]]
    """``(min, max)`` inclusive range for plausibility validation."""


@dataclass(frozen=True)
class ComponentSpec:
    """Describes one component of a :class:`ComponentVital`.

    Binds a single measured component (e.g. the systolic value of a blood
    pressure) to the vocabulary needed to represent it and to the name of the
    instance field that carries its value. These bindings are standard
    vocabularies (LOINC, UCUM) that live in the FHIR-free domain layer, so a
    mapper for any target (FHIR, or a future non-FHIR target) can build the
    component from this spec alone.
    """

    field_name: str
    """Name of the :class:`ComponentVital` instance attribute holding the value."""

    loinc_code: str
    """LOINC code for this component (e.g. ``"8480-6"`` for systolic)."""

    ucum_unit: str
    """UCUM unit for this component's value (e.g. ``"mm[Hg]"``)."""

    default_range: tuple[float, float]
    """``(min, max)`` inclusive plausibility bounds for this component.

    Used as the fallback range by the component range validator when no
    configuration override is supplied, mirroring
    :attr:`ScalarVital.plausible_range`.
    """


@dataclass(frozen=True, kw_only=True)
class ComponentVital(VitalSign):
    """Abstract base for multi-component vital signs (e.g. blood pressure).

    A concrete subclass declares its component *structure* as the ``components``
    class variable (an ordered tuple of :class:`ComponentSpec`) and carries each
    component *value* as a named, typed instance field whose name matches the
    corresponding ``ComponentSpec.field_name``. This mirrors how
    :class:`ScalarVital` pairs class metadata with a single instance ``value``,
    keeps the domain model strongly typed, and keeps LOINC/UCUM semantics in the
    FHIR-free domain layer.

    Concrete subclasses must additionally declare the inherited ``loinc_code``
    (the panel code) and ``us_core_profile`` class variables. Missing or
    inconsistent metadata raises ``TypeError`` at import time.
    """

    components: ClassVar[tuple[ComponentSpec, ...]]
    """Ordered component structure; declared by each concrete subclass."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Enforce the component contract only on concrete subclasses, identified
        # (like the ScalarVital/VitalSign contract) by their assigning a
        # ``loinc_code``. Abstract intermediaries leave it unassigned.
        if "loinc_code" in cls.__dict__:
            _check_component_specs(cls)

    def component_values(self) -> tuple[tuple[ComponentSpec, float], ...]:
        """Return ``(spec, value)`` pairs in declared order.

        This is the single, target-neutral surface that FHIR mappers, the
        component range validator, and duplicate detection use to read a
        component vital's values, so none of them need per-vital special-casing.

        Returns:
            A tuple of ``(ComponentSpec, float)`` pairs, one per declared
            component, in the order the components were declared.
        """
        return tuple(
            (spec, float(getattr(self, spec.field_name))) for spec in self.components
        )


def _check_component_specs(cls: type) -> None:
    """Raise ``TypeError`` if a concrete ``ComponentVital`` has invalid component metadata.

    A concrete component vital must declare a non-empty ``components`` tuple, and
    every ``ComponentSpec.field_name`` must correspond to an instance field
    declared on the class so ``component_values`` can read it.

    This runs from ``__init_subclass__``, which fires *before* ``@dataclass``
    processes the class body, so the fields are read from the annotations across
    the MRO (excluding ``ClassVar`` annotations) rather than from
    ``dataclasses.fields``, which is not yet populated at this point.
    """
    components = getattr(cls, "components", None)
    if not components:
        raise TypeError(f"{cls.__qualname__} must declare a non-empty 'components' ClassVar.")

    declared_fields = _instance_field_names(cls)
    missing = [spec.field_name for spec in components if spec.field_name not in declared_fields]
    if missing:
        raise TypeError(
            f"{cls.__qualname__} declares ComponentSpec field(s) with no matching "
            f"instance field: {', '.join(missing)}"
        )


def _instance_field_names(cls: type) -> set[str]:
    """Return instance-field names annotated on *cls* and its bases, excluding ClassVars.

    Used at class-creation time (from ``__init_subclass__``), before
    ``@dataclass`` has run, so it inspects raw annotations rather than dataclass
    fields. A ``ClassVar[...]`` annotation is treated as class metadata, not an
    instance field.
    """
    names: set[str] = set()
    for klass in cls.__mro__:
        annotations = klass.__dict__.get("__annotations__", {})
        for name, annotation in annotations.items():
            if _is_classvar_annotation(annotation):
                continue
            names.add(name)
    return names


def _is_classvar_annotation(annotation: object) -> bool:
    """Return ``True`` if *annotation* denotes a ``typing.ClassVar``.

    Handles both the string form (from ``from __future__ import annotations``,
    which stringifies annotations) and the actual ``ClassVar[...]`` object.
    """
    if isinstance(annotation, str):
        return annotation.startswith("ClassVar") or annotation.startswith("typing.ClassVar")
    return getattr(annotation, "__class__", None) is not None and str(annotation).startswith(
        "typing.ClassVar"
    )


class DeviceUserMatch(enum.Enum):
    """Whether a reading's device-assigned user ID belongs to the configured user.

    Multi-user blood-pressure cuffs and weight scales tag each reading with a
    one-byte user ID. The parser compares it with ``VOF_DEVICE_USER_ID`` and
    keeps only the outcome, so the ID itself never enters the domain object,
    logs, or FHIR (ADR-0004). A reading from a device that reports no user ID
    carries ``None`` instead of a member.
    """

    MATCH = "match"
    """The reported user ID equals the configured one."""

    MISMATCH = "mismatch"
    """The reported user ID differs, including the "unknown user" value ``0xFF``."""

    NOT_CONFIGURED = "not_configured"
    """The device reports a user ID, but no user ID is configured."""

    @classmethod
    def compare(cls, reported: int, expected: int | None) -> DeviceUserMatch:
        """Compare a reported device user ID with the configured one.

        Args:
            reported: The user ID decoded from the reading.
            expected: The configured user ID, or ``None`` when none is set.

        Returns:
            The match outcome. The IDs themselves are not kept.
        """
        if expected is None:
            return cls.NOT_CONFIGURED
        return cls.MATCH if reported == expected else cls.MISMATCH


@dataclass(frozen=True)
class DeviceInfo:
    """Immutable description of a physical or simulated device.

    Used by adapters to populate the FHIR Device resource. Not an ABC —
    instantiate directly.
    """

    manufacturer: str
    """Device manufacturer name (e.g. ``"Xiaomi"``)."""

    model: str
    """Device model name (e.g. ``"Smart Band 10"``)."""

    identifiers: dict[str, str]
    """Arbitrary key-value identifiers, e.g. ``{"bluetooth_address": "AA:BB:..."}``.

    Values must be strings; keys are identifier system names.
    """

    simulated: bool = False
    """``True`` for a device that produces simulated readings (the mock adapters).

    Its Device and Observations are labelled as test data (``HTEST``), so they can
    never be taken for real measurements (ADR-0002).
    """
