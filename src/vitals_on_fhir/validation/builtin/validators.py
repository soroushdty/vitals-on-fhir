# SPDX-License-Identifier: AGPL-3.0-or-later
"""Concrete validator implementations shipped with the package.

All three validators depend only on the Python standard library,
``vitals_on_fhir.vitals``, and ``vitals_on_fhir.validation.base``.
"""

from __future__ import annotations

from typing import ClassVar

from vitals_on_fhir.validation.base import ValidationResult, Validator
from vitals_on_fhir.vitals.base import ScalarVital, VitalSign


class PlausibleRangeValidator(Validator):
    """Rejects readings whose value falls outside a plausible numeric range.

    By default the allowed range is taken from the vital-sign class's
    ``plausible_range`` class variable.  A custom ``(min, max)`` pair may be
    supplied at construction time (e.g. from ``VOF_HR_MIN`` / ``VOF_HR_MAX``).

    Only :class:`~vitals_on_fhir.vitals.ScalarVital` subclasses carry a
    ``value``.  Non-scalar vitals are always accepted by this validator.
    """

    name: ClassVar[str] = "plausible_range"

    def __init__(self, hr_min: float | None = None, hr_max: float | None = None) -> None:
        """Optionally override the plausible range.

        Args:
            hr_min: Lower bound (inclusive).  Falls back to the vital class's
                ``plausible_range[0]`` when ``None``.
            hr_max: Upper bound (inclusive).  Falls back to the vital class's
                ``plausible_range[1]`` when ``None``.
        """
        self._hr_min = hr_min
        self._hr_max = hr_max

    def check(self, vital: VitalSign) -> ValidationResult:
        """Accept scalar vitals whose value is within bounds; pass non-scalars.

        Args:
            vital: The vital sign to evaluate.

        Returns:
            :class:`~vitals_on_fhir.validation.base.ValidationResult`
        """
        if not isinstance(vital, ScalarVital):
            return ValidationResult(accepted=True, validator_name=self.name)

        low = self._hr_min if self._hr_min is not None else vital.plausible_range[0]
        high = self._hr_max if self._hr_max is not None else vital.plausible_range[1]

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
        self._seen: set[tuple[str, object, float]] = set()

    def check(self, vital: VitalSign) -> ValidationResult:
        """Reject *vital* if the same reading has been seen before.

        Args:
            vital: The vital sign to evaluate.

        Returns:
            :class:`~vitals_on_fhir.validation.base.ValidationResult`
        """
        if not isinstance(vital, ScalarVital):
            return ValidationResult(accepted=True, validator_name=self.name)

        key = (vital.device_id, vital.effective, vital.value)
        if key in self._seen:
            return ValidationResult(
                accepted=False,
                validator_name=self.name,
                reason="duplicate reading already seen this session",
            )
        self._seen.add(key)
        return ValidationResult(accepted=True, validator_name=self.name)
