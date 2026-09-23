# SPDX-License-Identifier: AGPL-3.0-or-later
"""Domain model ABCs and value objects for vital signs.

This module is the root of the vitals hierarchy. It depends only on the Python
standard library — no other vitals_on_fhir packages are imported here.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar


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

    loinc_code: ClassVar[str]
    """LOINC code for the vital-sign concept (e.g. ``"8867-4"`` for heart rate)."""

    us_core_profile: ClassVar[str]
    """Canonical URL of the US Core profile this vital sign conforms to."""

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


@dataclass(frozen=True, kw_only=True)
class ComponentVital(VitalSign):
    """Abstract base for multi-component vital signs (e.g. blood pressure).

    No concrete subclass is defined in the MVP. The hierarchy is ready for
    roadmap additions (e.g. ``BloodPressure``) without breaking changes.
    """


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
