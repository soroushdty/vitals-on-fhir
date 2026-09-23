# SPDX-License-Identifier: AGPL-3.0-or-later
"""Concrete validator implementations shipped with the package.

All three validators depend only on the Python standard library,
``vitals_on_fhir.vitals``, and ``vitals_on_fhir.validation.base``.
"""

from __future__ import annotations

from typing import ClassVar

from vitals_on_fhir.validation.base import ValidationResult, Validator
from vitals_on_fhir.vitals.base import ComponentVital, ScalarVital, VitalSign


class PlausibleRangeValidator(Validator):
    """Rejects scalar readings whose value falls outside a plausible range.

    Bounds are resolved *per vital-sign class*: for a given reading, the
    validator looks up ``overrides[type(vital)]`` and, when no override is
    present for that class, falls back to the class's ``plausible_range`` class
    variable. This lets a single instance carry correct bounds for several
    scalar vitals at once (e.g. heart rate and oxygen saturation).

    For backward compatibility the legacy ``(hr_min, hr_max)`` positional form
    is retained: a bare ``(hr_min, hr_max)`` pair is translated internally into
    a ``{HeartRate: (hr_min, hr_max)}`` override, so existing construction and
    behavior are unchanged.

    Only :class:`~vitals_on_fhir.vitals.ScalarVital` subclasses carry a
    ``value``.  Non-scalar vitals are always accepted by this validator.
    """

    name: ClassVar[str] = "plausible_range"

    def __init__(
        self,
        hr_min: float | None = None,
        hr_max: float | None = None,
        *,
        overrides: dict[type, tuple[float, float]] | None = None,
    ) -> None:
        """Configure per-vital-class plausible-range overrides.

        Args:
            hr_min: Legacy lower bound (inclusive) for heart rate. When both
                ``hr_min`` and ``hr_max`` are supplied they are mapped to a
                ``HeartRate`` override, preserving the original single-pair form
                (e.g. from ``VOF_HR_MIN`` / ``VOF_HR_MAX``).
            hr_max: Legacy upper bound (inclusive) for heart rate; see ``hr_min``.
            overrides: Mapping from a vital-sign class to an inclusive
                ``(min, max)`` range. A class not present in the mapping falls
                back to its ``plausible_range`` class variable.
        """
        self._overrides: dict[type, tuple[float, float]] = dict(overrides or {})
        # Back-compat: a bare (hr_min, hr_max) maps to a HeartRate override.
        # Imported lazily so this module carries no hard dependency on a
        # specific builtin vital class.
        if hr_min is not None and hr_max is not None:
            from vitals_on_fhir.vitals.builtin.heart_rate import HeartRate

            self._overrides.setdefault(HeartRate, (hr_min, hr_max))

    def check(self, vital: VitalSign) -> ValidationResult:
        """Accept scalar vitals whose value is within bounds; pass non-scalars.

        Bounds are resolved from ``overrides[type(vital)]`` when present, else
        from the vital class's ``plausible_range``. The rejection reason names
        only the bounds, never the measurement value.

        Args:
            vital: The vital sign to evaluate.

        Returns:
            :class:`~vitals_on_fhir.validation.base.ValidationResult`
        """
        if not isinstance(vital, ScalarVital):
            return ValidationResult(accepted=True, validator_name=self.name)

        low, high = self._overrides.get(type(vital), vital.plausible_range)

        if low <= vital.value <= high:
            return ValidationResult(accepted=True, validator_name=self.name)

        return ValidationResult(
            accepted=False,
            validator_name=self.name,
            reason=f"value outside plausible range [{low}, {high}]",
        )


class SensorContactValidator(Validator):
    """Rejects readings where sensor contact is explicitly reported as absent.

    A value of ``None`` (sensor contact not reported by the device) is treated
    as acceptable.  Only ``sensor_contact is False`` triggers rejection.
    """

    name: ClassVar[str] = "sensor_contact"

    def check(self, vital: VitalSign) -> ValidationResult:
        """Reject only when ``vital.sensor_contact is False``.

        Args:
            vital: The vital sign to evaluate.

        Returns:
            :class:`~vitals_on_fhir.validation.base.ValidationResult`
        """
        sensor_contact = getattr(vital, "sensor_contact", None)
        if sensor_contact is False:
            return ValidationResult(
                accepted=False,
                validator_name=self.name,
                reason="sensor contact not detected",
            )
        return ValidationResult(accepted=True, validator_name=self.name)


class ComponentRangeValidator(Validator):
    """Rejects a component vital if any component value is outside its bounds.

    Bounds come from an optional per-``(vital_class, field_name)`` override
    mapping (wired from ``VOF_BP_*`` configuration in ``cli.py``); when no
    override is supplied for a component, its
    :attr:`~vitals_on_fhir.vitals.ComponentSpec.default_range` is used. This is
    the component-vital counterpart to :class:`PlausibleRangeValidator`, which
    only handles scalars.

    Non-component vitals are always accepted by this validator. Rejection
    reasons name the component and its bounds only, never the measurement value.
    """

    name: ClassVar[str] = "component_range"

    def __init__(
        self,
        overrides: dict[tuple[type, str], tuple[float, float]] | None = None,
    ) -> None:
        """Optionally override per-component plausible ranges.

        Args:
            overrides: Mapping from ``(vital_class, field_name)`` to an inclusive
                ``(min, max)`` range. A component not present in the mapping falls
                back to its ``ComponentSpec.default_range``.
        """
        self._overrides = overrides or {}

    def check(self, vital: VitalSign) -> ValidationResult:
        """Accept component vitals whose every component is in range; pass others.

        Args:
            vital: The vital sign to evaluate.

        Returns:
            :class:`~vitals_on_fhir.validation.base.ValidationResult`
        """
        if not isinstance(vital, ComponentVital):
            return ValidationResult(accepted=True, validator_name=self.name)

        vital_class = type(vital)
        for spec, value in vital.component_values():
            low, high = self._overrides.get(
                (vital_class, spec.field_name), spec.default_range
            )
            if not (low <= value <= high):
                return ValidationResult(
                    accepted=False,
                    validator_name=self.name,
                    reason=f"{spec.field_name} outside plausible range [{low}, {high}]",
                )
        return ValidationResult(accepted=True, validator_name=self.name)


class DuplicateValidator(Validator):
    """Rejects readings that are identical to one already seen this session.

    Identity is defined by the triple ``(device_id, effective, value)``.
    Non-scalar vitals (which have no ``value``) are never rejected as
    duplicates by this validator.

    The seen-set grows without bound during a session; it is cleared only
    when the validator instance is replaced (e.g. on process restart).
    """

    name: ClassVar[str] = "duplicate"

    def __init__(self) -> None:
        """Initialise an empty seen-set for this session."""
        self._seen: set[tuple[object, ...]] = set()

    def check(self, vital: VitalSign) -> ValidationResult:
        """Reject *vital* if the same reading has been seen before.

        Identity is the ``(device_id, effective, value)`` triple for a
        :class:`~vitals_on_fhir.vitals.ScalarVital` and
        ``(device_id, effective, component_values())`` for a
        :class:`~vitals_on_fhir.vitals.ComponentVital`. Both share the same
        exact-match seen-set. A component identity guards against a
        store-and-forward device re-sending the same buffered reading on
        reconnect. Vitals of any other shape are never treated as duplicates.

        Args:
            vital: The vital sign to evaluate.

        Returns:
            :class:`~vitals_on_fhir.validation.base.ValidationResult`
        """
        key = self._identity(vital)
        if key is None:
            return ValidationResult(accepted=True, validator_name=self.name)

        if key in self._seen:
            return ValidationResult(
                accepted=False,
                validator_name=self.name,
                reason="duplicate reading already seen this session",
            )
        self._seen.add(key)
        return ValidationResult(accepted=True, validator_name=self.name)

    def _identity(self, vital: VitalSign) -> tuple[object, ...] | None:
        """Return the exact-match identity key for *vital*, or ``None`` if unsupported."""
        if isinstance(vital, ScalarVital):
            return (vital.device_id, vital.effective, vital.value)
        if isinstance(vital, ComponentVital):
            return (vital.device_id, vital.effective, vital.component_values())
        return None
