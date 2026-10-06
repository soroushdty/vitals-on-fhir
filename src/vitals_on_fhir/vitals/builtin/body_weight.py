# SPDX-License-Identifier: AGPL-3.0-or-later
"""Concrete ``BodyWeight`` vital-sign class for standard-profile weight scales."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from vitals_on_fhir.vitals.base import DeviceUserMatch, ScalarVital


@dataclass(frozen=True, kw_only=True)
class BodyWeight(ScalarVital):
    """A single body-weight measurement in kilograms.

    Maps to LOINC ``29463-7`` ("Body weight") and conforms to the US Core Body
    Weight profile. A standard-profile Bluetooth Weight Scale reports weight as a
    single scalar quantity, so this is a scalar vital with a single ``value`` in
    kilograms (UCUM ``kg``); an Imperial (pounds) reading is normalized to
    kilograms by the parser before the reading is constructed.

    The default ``plausible_range`` of ``(2.0, 650.0)`` kg is a
    physical-plausibility bound, not a clinical threshold: it rejects values that
    could not have come from a real human on a home scale (a zero/empty-scale
    decode artifact, a wrong-unit misread) while admitting the full documented
    range of human body weight, whose heaviest recorded case is around 635 kg.
    """

    loinc_code: ClassVar[str] = "29463-7"
    ucum_unit: ClassVar[str] = "kg"
    us_core_profile: ClassVar[str] = (
        "http://hl7.org/fhir/us/core/StructureDefinition/us-core-body-weight"
    )
    plausible_range: ClassVar[tuple[float, float]] = (2.0, 650.0)

    device_user: DeviceUserMatch | None = None
    """Whether the device-assigned user ID matches ``VOF_DEVICE_USER_ID``.

    ``None`` means the device reports no user ID (a single-user device). The ID
    itself is never kept; see :class:`~vitals_on_fhir.vitals.DeviceUserMatch`.
    """
