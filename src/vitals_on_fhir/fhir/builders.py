# SPDX-License-Identifier: AGPL-3.0-or-later
"""FHIR resource builder functions.

Each function constructs and returns a ``fhir.resources`` model instance.
They are plain functions (not classes) and act as a thin construction layer
between the domain model and the FHIR library.

Resources target **FHIR R4 (4.0.1)** semantics, so the R4B-compatible models
under ``fhir.resources.R4B`` are used. ``fhir.resources`` is imported lazily
inside each function body; at module level its types are guarded by
``TYPE_CHECKING`` so this module stays importable without eagerly loading the
library. Resources are built with ``model_validate`` so pydantic validation
runs at construction time — invalid resources never leave a builder.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from vitals_on_fhir.vitals.base import DeviceInfo

if TYPE_CHECKING:
    from fhir.resources.R4B.capabilitystatement import CapabilityStatement
    from fhir.resources.R4B.device import Device
    from fhir.resources.R4B.operationoutcome import OperationOutcome
    from fhir.resources.R4B.patient import Patient


# FHIR version this server speaks; R4 4.0.1 per the project's FHIR conventions.
_FHIR_VERSION = "4.0.1"

# Publication date used for the CapabilityStatement (year-month granularity is
# sufficient; a fixed date keeps the statement stable across restarts).
_CAPABILITY_STATEMENT_DATE = "2026-09-01"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    """Return a stable, URL-safe slug derived from *value*.

    Lowercases, replaces any run of non-alphanumeric characters with a single
    hyphen, and strips leading/trailing hyphens. Deterministic: the same input
    always yields the same slug, so a Device id stays stable across restarts.

    Args:
        value: The source string (e.g. a device model name).

    Returns:
        A slug such as ``"smart-band-10"``. Falls back to ``"device"`` when the
        input has no alphanumeric characters.
    """
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")
    return slug or "device"


def build_device(device_info: DeviceInfo) -> Device:
    """Construct a FHIR R4 Device resource from *device_info*.

    The Device ``id`` is a stable slug derived from ``device_info.model`` so it
    is deterministic across restarts within a session. Each entry in
    ``device_info.identifiers`` becomes a FHIR ``identifier`` (its key is used
    as the identifier ``system`` and its value as the identifier ``value``).

    Args:
        device_info: Immutable description of the physical or simulated device.

    Returns:
        A ``fhir.resources.R4B.device.Device`` instance populated with the
        device's manufacturer, model, and identifiers.
    """
    from fhir.resources.R4B.device import Device

    data: dict[str, object] = {
        "id": _slugify(device_info.model),
        "manufacturer": device_info.manufacturer,
        "deviceName": [{"name": device_info.model, "type": "model-name"}],
    }
    identifiers = [
        {"system": system, "value": value}
        for system, value in device_info.identifiers.items()
    ]
    if identifiers:
        data["identifier"] = identifiers
    return Device.model_validate(data)


def build_patient(patient_id: str) -> Patient:
    """Construct a FHIR R4 Patient resource for the local synthetic patient.

    The Patient is deliberately minimal: it carries only ``id`` and no clinical
    data. ``VOF_PATIENT_ID`` is a local synthetic identifier, not a real patient
    identifier.

    Args:
        patient_id: The local patient identifier (``VOF_PATIENT_ID``).

    Returns:
        A ``fhir.resources.R4B.patient.Patient`` instance with ``id`` set to
        *patient_id*.
    """
    from fhir.resources.R4B.patient import Patient

    return Patient.model_validate({"id": patient_id})


def build_capability_statement() -> CapabilityStatement:
    """Construct the FHIR R4 CapabilityStatement for this server.

    Documents the read-only Observation / Patient / Device endpoints and the
    Observation search parameters supported by the API (``code``, ``date``,
    ``_sort``, ``_count``). No write interactions are advertised.

    Returns:
        A ``fhir.resources.R4B.capabilitystatement.CapabilityStatement``
        describing the read-only endpoints supported by the vitals-on-fhir API.
    """
    from fhir.resources.R4B.capabilitystatement import CapabilityStatement

    data: dict[str, object] = {
        "status": "active",
        "date": _CAPABILITY_STATEMENT_DATE,
        "kind": "instance",
        "fhirVersion": _FHIR_VERSION,
        "format": ["application/fhir+json"],
        "rest": [
            {
                "mode": "server",
                "documentation": (
                    "Read-only FHIR R4 API for locally acquired vital signs. "
                    "All requests require a bearer token."
                ),
                "resource": [
                    {
                        "type": "Observation",
                        "interaction": [
                            {"code": "read"},
                            {"code": "search-type"},
                        ],
                        "searchParam": [
                            {
                                "name": "code",
                                "type": "token",
                                "documentation": (
                                    "Filter by 'system|code', "
                                    "e.g. http://loinc.org|8867-4."
                                ),
                            },
                            {
                                "name": "date",
                                "type": "date",
                                "documentation": (
                                    "Filter by effectiveDateTime; supports the "
                                    "ge, le, gt, and lt prefixes."
                                ),
                            },
                            {
                                "name": "_sort",
                                "type": "special",
                                "documentation": (
                                    "Only '-date' (descending effectiveDateTime) "
                                    "is supported."
                                ),
                            },
                            {
                                "name": "_count",
                                "type": "number",
                                "documentation": "Limit the size of the result set.",
                            },
                        ],
                    },
                    {
                        "type": "Patient",
                        "interaction": [{"code": "read"}],
                    },
                    {
                        "type": "Device",
                        "interaction": [{"code": "read"}],
                    },
                ],
            }
        ],
    }
    return CapabilityStatement.model_validate(data)


def build_operation_outcome(
    severity: str,
    code: str,
    diagnostics: str,
) -> OperationOutcome:
    """Construct a FHIR R4 OperationOutcome resource.

    The outcome carries exactly one issue. Callers must never pass secrets
    (e.g. ``VOF_API_TOKEN``) or measurement values in *diagnostics*; the
    message is intended for human-readable, non-sensitive detail only.

    Args:
        severity: Issue severity (e.g. ``"error"``, ``"warning"``).
        code: Issue-type code (e.g. ``"security"``, ``"not-found"``, ``"invalid"``).
        diagnostics: Human-readable diagnostic message, free of secrets and
            measurement values.

    Returns:
        A ``fhir.resources.R4B.operationoutcome.OperationOutcome`` with a single
        issue populated from the supplied arguments.
    """
    from fhir.resources.R4B.operationoutcome import OperationOutcome

    return OperationOutcome.model_validate(
        {
            "issue": [
                {
                    "severity": severity,
                    "code": code,
                    "diagnostics": diagnostics,
                }
            ]
        }
    )
