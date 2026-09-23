# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validation ABCs, result type, and the validator chain.

This module depends only on the Python standard library and ``vitals_on_fhir.vitals``.
No imports from ``adapters``, ``fhir``, ``pipeline``, ``store``, ``api``, or ``dashboard``.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import ClassVar

from vitals_on_fhir.vitals.base import VitalSign


@dataclass(frozen=True)
class ValidationResult:
    """Immutable outcome of a single validator's check.

    Attributes:
        accepted: ``True`` if the vital sign passed validation.
        validator_name: Name of the validator that produced this result.
        reason: Human-readable explanation when ``accepted`` is ``False``.
    """

    accepted: bool
    validator_name: str
    reason: str | None = None


class Validator(abc.ABC):
    """Abstract base for a single validation rule.

    Concrete subclasses must declare a ``name`` class variable and implement
    :meth:`check`.
    """

    name: ClassVar[str]
    """Short identifier for this validator (used in :class:`ValidationResult`)."""

    @abc.abstractmethod
    def check(self, vital: VitalSign) -> ValidationResult:
        """Evaluate *vital* against this validator's rule.

        Args:
            vital: The :class:`~vitals_on_fhir.vitals.VitalSign` to evaluate.

        Returns:
            A :class:`ValidationResult` indicating acceptance or rejection.
        """
        ...


class ValidatorChain:
    """Runs a sequence of :class:`Validator` instances in registration order.

    Returns the first rejection encountered, or an accepted result if all
    validators pass.  Not an ABC — instantiate directly.

    Example::

        chain = ValidatorChain([PlausibleRangeValidator(), SensorContactValidator()])
        result = chain.run(heart_rate_reading)
    """

    def __init__(self, validators: list[Validator]) -> None:
        """Initialise the chain with an ordered list of validators.

        Args:
            validators: Validators applied left-to-right; first rejection wins.
        """
        self._validators = list(validators)

    def run(self, vital: VitalSign) -> ValidationResult:
        """Run every validator against *vital*, stopping at the first rejection.

        Args:
            vital: The :class:`~vitals_on_fhir.vitals.VitalSign` to validate.

        Returns:
            The first :class:`ValidationResult` with ``accepted=False``, or an
            accepted :class:`ValidationResult` if all validators pass.
        """
        for validator in self._validators:
            result = validator.check(vital)
            if not result.accepted:
                return result
        return ValidationResult(accepted=True, validator_name="chain")
