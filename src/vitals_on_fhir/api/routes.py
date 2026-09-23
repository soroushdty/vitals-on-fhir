# SPDX-License-Identifier: AGPL-3.0-or-later
"""FHIR REST API route functions.

Each function is a plain ``async def`` — no route classes.  The
:class:`~vitals_on_fhir.store.ObservationStore`, the
:class:`~vitals_on_fhir.api.auth.Authenticator`, and the startup-built
``Patient`` / ``Device`` resources are injected via :func:`fastapi.Depends`
rather than module-level singletons.  The dependency provider callables defined
here (:func:`get_store`, :func:`get_authenticator`, :func:`get_patient_resource`,
:func:`get_device_resource`) are placeholders that the composition root wires up
through ``app.dependency_overrides`` in :mod:`vitals_on_fhir.api.app`; calling an
unconfigured provider raises so a missing wiring fails loudly rather than
silently serving nothing.

Endpoint catalogue (all require a valid ``Authorization: Bearer <token>``):

- ``GET /fhir/metadata``           — CapabilityStatement
- ``GET /fhir/Observation``        — searchset Bundle (filters: code, date, _sort, _count)
- ``GET /fhir/Observation/{id}``   — single Observation
- ``GET /fhir/Patient/{id}``       — single Patient
- ``GET /fhir/Device/{id}``        — single Device

Every response (success or error) carries ``Content-Type: application/fhir+json``.
Authentication failures return HTTP 401 with an ``OperationOutcome`` (issue code
``security``) — never 403.  Unknown resource ids return HTTP 404 with an
``OperationOutcome`` (issue code ``not-found``).  No write operations exist.

Allowed imports: stdlib, ``fastapi``, ``store/``, ``fhir/``, ``vitals/``.
Must NOT import from ``adapters``, ``validation``, ``pipeline``,
``dashboard``, or ``cli``.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from vitals_on_fhir.api.auth import Authenticator
from vitals_on_fhir.fhir import build_capability_statement, build_operation_outcome
from vitals_on_fhir.store import ObservationStore

if TYPE_CHECKING:
    from fhir.resources.R4B.device import Device
    from fhir.resources.R4B.patient import Patient
    from fhir.resources.R4B.resource import Resource


#: Media type mandated for every FHIR response (FR-11).
FHIR_MEDIA_TYPE = "application/fhir+json"

#: Recognised ``date`` search-parameter prefixes and how each maps onto the
#: store's inclusive ``date_from`` / ``date_to`` bounds.
_DATE_PREFIXES = ("ge", "le", "gt", "lt")

# Bearer-token extractor.  ``auto_error=False`` so a missing header does not
# raise FastAPI's default 403; we translate every failure to 401 ourselves.
_bearer_scheme = HTTPBearer(auto_error=False)


class FhirHttpError(Exception):
    """Route-level error rendered as a FHIR ``OperationOutcome``.

    The composition root registers an exception handler for this type (see
    :func:`vitals_on_fhir.api.app.create_app`) so the response body is an
    ``OperationOutcome`` served as ``application/fhir+json`` with the given
    status code.  Instances never carry secrets or measurement values in
    *diagnostics*.

    Args:
        status_code: HTTP status code to return (e.g. ``401``, ``404``).
        issue_code: FHIR issue-type code (e.g. ``"security"``, ``"not-found"``).
        diagnostics: Human-readable, non-sensitive diagnostic message.
        severity: FHIR issue severity; defaults to ``"error"``.
    """

    def __init__(
        self,
        status_code: int,
        issue_code: str,
        diagnostics: str,
        severity: str = "error",
    ) -> None:
        super().__init__(diagnostics)
        self.status_code = status_code
        self.issue_code = issue_code
        self.diagnostics = diagnostics
        self.severity = severity


# ----------------------------------------------------------------------------
# Dependency providers (overridden by the composition root in app.py)
# ----------------------------------------------------------------------------


def get_store() -> ObservationStore:
    """Provide the :class:`ObservationStore` for route handlers.

    This is a placeholder overridden via ``app.dependency_overrides`` in
    :func:`vitals_on_fhir.api.app.create_app`; the concrete store is created in
    ``cli.py`` and injected there.  Calling it unconfigured raises so missing
    wiring is obvious.

    Raises:
        RuntimeError: Always, unless overridden by the application factory.
    """
    raise RuntimeError("ObservationStore dependency is not configured")


def get_authenticator() -> Authenticator:
    """Provide the :class:`Authenticator` for the bearer-token dependency.

    Placeholder overridden via ``app.dependency_overrides``; the concrete
    authenticator is created in ``cli.py`` and injected there.

    Raises:
        RuntimeError: Always, unless overridden by the application factory.
    """
    raise RuntimeError("Authenticator dependency is not configured")


def get_patient_resource() -> Patient:
    """Provide the startup-built FHIR ``Patient`` resource.

    Placeholder overridden via ``app.dependency_overrides``; the resource is
    built once in ``cli.py`` from ``VOF_PATIENT_ID`` and injected there.

    Raises:
        RuntimeError: Always, unless overridden by the application factory.
    """
    raise RuntimeError("Patient resource dependency is not configured")


def get_device_resource() -> Device:
    """Provide the startup-built FHIR ``Device`` resource.

    Placeholder overridden via ``app.dependency_overrides``; the resource is
    built once in ``cli.py`` from ``adapter.device_info`` and injected there.

    Raises:
        RuntimeError: Always, unless overridden by the application factory.
    """
    raise RuntimeError("Device resource dependency is not configured")


# ----------------------------------------------------------------------------
# Authentication dependency
# ----------------------------------------------------------------------------


async def require_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    authenticator: Annotated[Authenticator, Depends(get_authenticator)],
) -> None:
    """Enforce a valid bearer token on a request.

    Extracts the ``Authorization: Bearer <token>`` credentials and validates
    them with the injected :class:`Authenticator`.  A missing or invalid token
    raises a :class:`FhirHttpError` mapped to HTTP 401 with an
    ``OperationOutcome`` (issue code ``security``) — never 403 (FR-12).  The
    token value is never logged or echoed.

    Args:
        credentials: Parsed bearer credentials, or ``None`` when absent.
        authenticator: The injected authenticator used for the constant-time
            token comparison.

    Raises:
        FhirHttpError: With status 401 when the token is missing or invalid.
    """
    token = credentials.credentials if credentials is not None else ""
    if not token or not authenticator.authenticate(token):
        raise FhirHttpError(
            status_code=401,
            issue_code="security",
            diagnostics="Authentication required: a valid bearer token must be provided.",
        )


# A dependency that authenticates but yields nothing, applied to every route.
_AuthDep = Depends(require_token)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def fhir_response(resource: Resource, status_code: int = 200) -> Response:
    """Serialise a ``fhir.resources`` model as an ``application/fhir+json`` response.

    Uses the library's own ``model_dump_json`` so serialisation is never done
    by hand.

    Args:
        resource: Any ``fhir.resources`` model instance.
        status_code: HTTP status code; defaults to ``200``.

    Returns:
        A :class:`fastapi.Response` whose body is the resource's FHIR JSON and
        whose media type is ``application/fhir+json``.
    """
    return Response(
        content=resource.model_dump_json(),
        status_code=status_code,
        media_type=FHIR_MEDIA_TYPE,
    )


def _parse_date_param(value: str | None) -> tuple[datetime | None, datetime | None]:
    """Translate a FHIR ``date`` search parameter into store bounds.

    Recognises the ``ge`` / ``le`` / ``gt`` / ``lt`` prefixes and maps them onto
    inclusive ``(date_from, date_to)`` bounds understood by the store.  ``gt``
    and ``lt`` are treated as their inclusive counterparts because the store
    exposes only inclusive bounds; this is a conservative, well-defined
    interpretation for the MVP.  A value that does not parse as ISO 8601 is
    ignored (treated as unsupported), returning ``(None, None)`` (FR-11).

    Args:
        value: The raw ``date`` query-parameter value, or ``None``.

    Returns:
        A ``(date_from, date_to)`` tuple; either element may be ``None``.
    """
    if value is None:
        return None, None

    prefix = ""
    raw = value
    for candidate in _DATE_PREFIXES:
        if value.startswith(candidate):
            prefix = candidate
            raw = value[len(candidate) :]
            break

    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return None, None

    if prefix in ("ge", "gt"):
        return moment, None
    if prefix in ("le", "lt"):
        return None, moment
    # No recognised prefix: match the exact instant on both bounds.
    return moment, moment


def _parse_code_param(value: str | None) -> str | None:
    """Extract the bare LOINC code from a FHIR ``token`` search parameter.

    Accepts either a plain ``code`` or the ``system|code`` token form and
    returns just the ``code`` portion, which is what the store filters on.

    Args:
        value: The raw ``code`` query-parameter value, or ``None``.

    Returns:
        The bare code, or ``None`` when *value* is ``None``.
    """
    if value is None:
        return None
    if "|" in value:
        return value.split("|", 1)[1]
    return value


# ----------------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------------

router = APIRouter()


@router.get("/fhir/metadata", dependencies=[_AuthDep])
async def get_metadata() -> Response:
    """Return the FHIR R4 CapabilityStatement for this server.

    Describes the read-only Observation / Patient / Device endpoints and the
    supported Observation search parameters (FR-11).

    Returns:
        The CapabilityStatement as ``application/fhir+json``.
    """
    return fhir_response(build_capability_statement())


@router.get("/fhir/Observation", dependencies=[_AuthDep])
async def search_observations(
    request: Request,
    store: Annotated[ObservationStore, Depends(get_store)],
    code: Annotated[str | None, Query()] = None,
    date: Annotated[str | None, Query()] = None,
    sort: Annotated[str | None, Query(alias="_sort")] = None,
    count: Annotated[int | None, Query(alias="_count", ge=0)] = None,
) -> Response:
    """Search stored FHIR Observations and return a searchset ``Bundle``.

    Supported parameters (all optional): ``code`` (``system|code`` or bare
    code), ``date`` (with ``ge`` / ``le`` / ``gt`` / ``lt`` prefixes),
    ``_sort=-date`` (descending ``effectiveDateTime``), and ``_count`` (page
    size).  Unsupported parameters are ignored without error (FR-11).  The
    Bundle ``total`` reflects the number of matching Observations, not the page
    size, and each entry carries a ``fullUrl`` and the full Observation
    ``resource``.

    Args:
        request: The incoming request, used to build absolute ``fullUrl`` values.
        store: The injected observation store.
        code: FHIR ``token`` filter on the Observation code.
        date: FHIR ``date`` filter on ``effectiveDateTime``.
        sort: FHIR ``_sort``; only ``-date`` (descending) is honoured.
        count: FHIR ``_count`` page-size limit.

    Returns:
        A searchset ``Bundle`` as ``application/fhir+json``.
    """
    from fhir.resources.R4B.bundle import Bundle

    loinc_code = _parse_code_param(code)
    date_from, date_to = _parse_date_param(date)
    sort_desc = sort == "-date"

    matches = await store.search(
        code=loinc_code,
        date_from=date_from,
        date_to=date_to,
        sort_desc=sort_desc,
        count=count,
    )

    base = str(request.base_url).rstrip("/")
    entries = [
        {
            "fullUrl": f"{base}/fhir/Observation/{observation.id}",
            "resource": observation.model_dump(),
        }
        for observation in matches
    ]
    bundle = Bundle.model_validate(
        {
            "type": "searchset",
            "total": len(matches),
            "entry": entries,
        }
    )
    return fhir_response(bundle)


@router.get("/fhir/Observation/{observation_id}", dependencies=[_AuthDep])
async def get_observation(
    store: Annotated[ObservationStore, Depends(get_store)],
    observation_id: Annotated[str, Path()],
) -> Response:
    """Return a single FHIR Observation by logical ID.

    Args:
        store: The injected observation store.
        observation_id: The ``id`` field of the target Observation.

    Returns:
        The matching Observation as ``application/fhir+json``.

    Raises:
        FhirHttpError: With status 404 (issue code ``not-found``) when absent.
    """
    observation = await store.get(observation_id)
    if observation is None:
        raise FhirHttpError(
            status_code=404,
            issue_code="not-found",
            diagnostics=f"Observation '{observation_id}' was not found.",
        )
    return fhir_response(observation)


@router.get("/fhir/Patient/{patient_id}", dependencies=[_AuthDep])
async def get_patient(
    patient: Annotated[Any, Depends(get_patient_resource)],
    patient_id: Annotated[str, Path()],
) -> Response:
    """Return the FHIR Patient resource for the given ID.

    Only the single startup-built local Patient exists in the MVP; any other id
    yields 404.

    Args:
        patient: The injected startup-built Patient resource.
        patient_id: The requested patient identifier.

    Returns:
        The FHIR Patient resource as ``application/fhir+json``.

    Raises:
        FhirHttpError: With status 404 (issue code ``not-found``) when the id
            does not match the configured Patient.
    """
    if str(patient.id) != patient_id:
        raise FhirHttpError(
            status_code=404,
            issue_code="not-found",
            diagnostics=f"Patient '{patient_id}' was not found.",
        )
    return fhir_response(patient)


@router.get("/fhir/Device/{device_id}", dependencies=[_AuthDep])
async def get_device(
    device: Annotated[Any, Depends(get_device_resource)],
    device_id: Annotated[str, Path()],
) -> Response:
    """Return the FHIR Device resource for the given ID.

    Only the single startup-built Device exists in the MVP; any other id yields
    404.

    Args:
        device: The injected startup-built Device resource.
        device_id: The requested device identifier.

    Returns:
        The FHIR Device resource as ``application/fhir+json``.

    Raises:
        FhirHttpError: With status 404 (issue code ``not-found``) when the id
            does not match the configured Device.
    """
    if str(device.id) != device_id:
        raise FhirHttpError(
            status_code=404,
            issue_code="not-found",
            diagnostics=f"Device '{device_id}' was not found.",
        )
    return fhir_response(device)


async def fhir_error_handler(_request: Request, exc: FhirHttpError) -> Response:
    """Render a :class:`FhirHttpError` as a FHIR ``OperationOutcome`` response.

    Registered on the FastAPI app by :func:`vitals_on_fhir.api.app.create_app`
    so authentication (401) and not-found (404) errors carry an
    ``OperationOutcome`` body served as ``application/fhir+json``.  The
    diagnostics never contain secrets or measurement values.

    Args:
        _request: The request that triggered the error (unused).
        exc: The raised :class:`FhirHttpError`.

    Returns:
        A :class:`fastapi.Response` with the OperationOutcome and the error's
        status code.
    """
    outcome = build_operation_outcome(
        severity=exc.severity,
        code=exc.issue_code,
        diagnostics=exc.diagnostics,
    )
    return fhir_response(outcome, status_code=exc.status_code)
