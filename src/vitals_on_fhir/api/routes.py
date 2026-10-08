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

import re
from datetime import UTC, datetime, timedelta, timezone
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

#: FHIR ``date`` search prefixes this server supports.
_DATE_PREFIXES = ("eq", "ge", "gt", "le", "lt")

#: Valid FHIR ``date`` prefixes this server does not support.
_UNSUPPORTED_DATE_PREFIXES = ("ne", "sa", "eb", "ap")

#: A FHIR ``date`` / ``dateTime`` search value at any precision from a year to
#: fractions of a second.  A space may stand for the ``+`` of a UTC offset,
#: because an unencoded ``+`` in a query string decodes to a space.
_FHIR_DATE = re.compile(
    r"(?P<year>\d{4})"
    r"(?:-(?P<month>\d{2})"
    r"(?:-(?P<day>\d{2})"
    r"(?:T(?P<hour>\d{2}):(?P<minute>\d{2})"
    r"(?::(?P<second>\d{2})(?:\.(?P<fraction>\d+))?)?"
    r"(?P<offset>Z|[+\- ]\d{2}:\d{2})?"
    r")?)?)?"
)

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
    token value is never logged or echoed.  An authenticator that does not
    require credentials (demo mode) lets every request through.

    Args:
        credentials: Parsed bearer credentials, or ``None`` when absent.
        authenticator: The injected authenticator used for the constant-time
            token comparison.

    Raises:
        FhirHttpError: With status 401 when the token is missing or invalid.
    """
    if not authenticator.requires_credentials:
        return
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


def _date_range(raw: str) -> tuple[datetime, datetime]:
    """Return the half-open range ``[start, end)`` a FHIR date value covers.

    The value's precision sets the range: ``2026`` is the whole year,
    ``2026-10-07`` the whole day, ``2026-10-07T12:00:00`` one second.  A value
    without a UTC offset is read as UTC.

    Args:
        raw: The search value without its prefix.

    Returns:
        The timezone-aware ``(start, end)`` of the range.

    Raises:
        ValueError: If *raw* is not a valid FHIR date or dateTime.
        OverflowError: If the range ends past the largest representable date.
    """
    match = _FHIR_DATE.fullmatch(raw)
    if match is None:
        msg = "not a FHIR date"
        raise ValueError(msg)
    part = match.groupdict()

    tz: timezone = UTC
    offset = part["offset"]
    if offset is not None and offset != "Z":
        sign = -1 if offset[0] == "-" else 1
        hours, minutes = int(offset[1:3]), int(offset[4:6])
        tz = timezone(sign * timedelta(hours=hours, minutes=minutes))

    year = int(part["year"])
    if part["month"] is None:
        return datetime(year, 1, 1, tzinfo=tz), datetime(year + 1, 1, 1, tzinfo=tz)
    month = int(part["month"])
    if part["day"] is None:
        start = datetime(year, month, 1, tzinfo=tz)
        end = datetime(year + month // 12, month % 12 + 1, 1, tzinfo=tz)
        return start, end
    day = int(part["day"])
    if part["hour"] is None:
        start = datetime(year, month, day, tzinfo=tz)
        return start, start + timedelta(days=1)

    second = microsecond = 0
    if part["second"] is None:
        width = timedelta(minutes=1)
    elif part["fraction"] is None:
        second = int(part["second"])
        width = timedelta(seconds=1)
    else:
        second = int(part["second"])
        digits = part["fraction"][:6]  # datetime resolves microseconds
        microsecond = int(digits.ljust(6, "0"))
        width = timedelta(microseconds=10 ** (6 - len(digits)))
    start = datetime(
        year, month, day, int(part["hour"]), int(part["minute"]), second, microsecond, tzinfo=tz
    )
    return start, start + width


def _parse_date_params(values: list[str] | None) -> tuple[datetime | None, datetime | None]:
    """Translate FHIR ``date`` search parameters into store bounds.

    Each value covers the range its precision implies (see
    :func:`_date_range`); its prefix compares that range with the
    Observation's ``effectiveDateTime`` instant ``t``:

    - ``eq`` (or no prefix): ``start <= t < end``
    - ``ge``: ``t >= start``;  ``gt``: ``t >= end``
    - ``le``: ``t < end``;  ``lt``: ``t < start``

    Repeated parameters must all match (``date=ge2026-10-01&date=lt2026-11-01``),
    so their bounds are intersected.

    Args:
        values: Every ``date`` query-parameter value, or ``None``.

    Returns:
        ``(date_from, date_before)``: the inclusive lower and exclusive upper
        bounds; either may be ``None``.

    Raises:
        FhirHttpError: With status 400 when a value is not a valid FHIR date or
            its prefix is not supported (FR-11).
    """
    date_from: datetime | None = None
    date_before: datetime | None = None
    for value in values or []:
        prefix, raw = value[:2], value[2:]
        if not prefix.isalpha():
            prefix, raw = "eq", value
        if prefix in _UNSUPPORTED_DATE_PREFIXES:
            raise FhirHttpError(
                status_code=400,
                issue_code="not-supported",
                diagnostics=(
                    f"The date prefix '{prefix}' is not supported; use eq, ge, gt, le, or lt."
                ),
            )
        try:
            if prefix not in _DATE_PREFIXES:
                msg = "unknown prefix"
                raise ValueError(msg)
            start, end = _date_range(raw)
        except (ValueError, OverflowError):
            raise FhirHttpError(
                status_code=400,
                issue_code="invalid",
                diagnostics=f"'{value}' is not a valid FHIR date search value.",
            ) from None

        low, high = {
            "eq": (start, end),
            "ge": (start, None),
            "gt": (end, None),
            "le": (None, end),
            "lt": (None, start),
        }[prefix]
        if low is not None and (date_from is None or low > date_from):
            date_from = low
        if high is not None and (date_before is None or high < date_before):
            date_before = high
    return date_from, date_before


def _parse_code_param(value: str | None) -> tuple[str | None, str | None]:
    """Split a FHIR ``token`` search value into ``(system, code)``.

    - ``code``: any system, so ``(None, code)``
    - ``system|code``: ``(system, code)``
    - ``|code``: a coding without a system, so ``("", code)``
    - ``system|``: any code in the system, so ``(system, None)``

    Args:
        value: The raw ``code`` query-parameter value, or ``None``.

    Returns:
        The ``(system, code)`` filters for the store; ``None`` matches anything.
    """
    if value is None:
        return None, None
    if "|" not in value:
        return None, value
    system, code = value.split("|", 1)
    return system, code or None


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
    date: Annotated[list[str] | None, Query()] = None,
    sort: Annotated[str | None, Query(alias="_sort")] = None,
    count: Annotated[int | None, Query(alias="_count", ge=0)] = None,
) -> Response:
    """Search stored FHIR Observations and return a searchset ``Bundle``.

    Supported parameters (all optional): ``code`` (a FHIR token: ``code``,
    ``system|code``, ``|code``, or ``system|``), ``date`` (at any precision,
    with the ``eq`` / ``ge`` / ``gt`` / ``le`` / ``lt`` prefixes; repeat it for
    a range), ``_sort=-date`` (descending ``effectiveDateTime``), and ``_count`` (page
    size).  Unsupported parameters are ignored without error (FR-11).  The
    Bundle ``total`` reflects the number of matching Observations, not the page
    size, and each entry carries a ``fullUrl`` and the full Observation
    ``resource``.

    Args:
        request: The incoming request, used to build absolute ``fullUrl`` values.
        store: The injected observation store.
        code: FHIR ``token`` filter on the Observation code.
        date: FHIR ``date`` filters on ``effectiveDateTime``, all of which
            must match.
        sort: FHIR ``_sort``; only ``-date`` (descending) is honoured.
        count: FHIR ``_count`` page-size limit.

    Returns:
        A searchset ``Bundle`` as ``application/fhir+json``.

    Raises:
        FhirHttpError: With status 400 when a ``date`` value is invalid or uses
            an unsupported prefix.
    """
    from fhir.resources.R4B.bundle import Bundle

    system, code_value = _parse_code_param(code)
    date_from, date_before = _parse_date_params(date)
    sort_desc = sort == "-date"

    # ``_count`` limits the page, not the match count: search without it so
    # ``total`` counts every match, then cut the page from the same snapshot.
    matches = await store.search(
        code=code_value,
        system=system,
        date_from=date_from,
        date_before=date_before,
        sort_desc=sort_desc,
    )
    page = matches if count is None else matches[:count]

    base = str(request.base_url).rstrip("/")
    entries = [
        {
            "fullUrl": f"{base}/fhir/Observation/{observation.id}",
            "resource": observation.model_dump(),
        }
        for observation in page
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
