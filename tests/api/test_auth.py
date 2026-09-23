# SPDX-License-Identifier: AGPL-3.0-or-later
"""API authentication tests (task 9.4).

Exercises the bearer-token auth layer of the read-only FHIR API through the
ASGI app returned by :func:`vitals_on_fhir.api.app.create_app`, driven by
``httpx.AsyncClient`` over an in-process :class:`httpx.ASGITransport` — no live
server is ever started (see ``testing.md`` "API authentication tests").

Covers **Property 13: Auth rejects every non-matching token** plus the
no-header / wrong-token / correct-token / unknown-id example cases from the
task, and asserts every FHIR response carries ``application/fhir+json`` and
that auth failures are HTTP 401 with an ``OperationOutcome`` (issue code
``security``) — never 403.

Validates: Requirements FR-12.1, FR-12.2, FR-12.3, FR-12.4.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable
from typing import TYPE_CHECKING

import httpx
from hypothesis import given, settings
from hypothesis import strategies as st

from vitals_on_fhir.api.app import create_app
from vitals_on_fhir.api.auth import StaticTokenAuthenticator
from vitals_on_fhir.fhir import build_device, build_patient
from vitals_on_fhir.store import InMemoryObservationStore
from vitals_on_fhir.vitals.base import DeviceInfo

if TYPE_CHECKING:
    from fastapi import FastAPI

# Synthetic token — never a real credential (security-privacy.md).
_TOKEN = "test-token-do-not-use"
_PATIENT_ID = "local-patient"
_FHIR_MEDIA_TYPE = "application/fhir+json"


class _FakeBroadcaster:
    """Minimal broadcaster satisfying ``BroadcasterLike`` for app construction.

    The WebSocket endpoint is not exercised by these HTTP tests; this fake just
    provides the async ``register`` / ``unregister`` methods ``create_app``
    requires so no real ``DashboardBroadcaster`` (a ``dashboard`` import) is
    needed here.
    """

    async def register(self, websocket: object) -> None:
        """No-op registration."""

    async def unregister(self, websocket: object) -> None:
        """No-op unregistration."""


def _build_app() -> FastAPI:
    """Build a fully wired app with a synthetic token and empty store."""
    device_info = DeviceInfo(
        manufacturer="Mock",
        model="Mock Device",
        identifiers={"mock_id": "mock-0001"},
    )
    return create_app(
        store=InMemoryObservationStore(max_size=100),
        authenticator=StaticTokenAuthenticator(_TOKEN),
        broadcaster=_FakeBroadcaster(),
        patient=build_patient(_PATIENT_ID),
        device=build_device(device_info),
    )


def _run[T](coro: Awaitable[T]) -> T:
    """Run *coro* to completion on a fresh event loop (no live server)."""
    return asyncio.run(coro)  # type: ignore[arg-type]


async def _request(
    app: FastAPI,
    path: str,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Issue a GET against *app* over an in-process ASGI transport."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers)


def _assert_security_401(response: httpx.Response) -> None:
    """Assert *response* is a 401 OperationOutcome with issue code ``security``."""
    # Never 403 — the client has not authenticated (security-privacy.md).
    assert response.status_code == 401
    assert response.status_code != 403
    assert response.headers["content-type"].startswith(_FHIR_MEDIA_TYPE)
    body = json.loads(response.content)
    assert body["resourceType"] == "OperationOutcome"
    assert body["issue"][0]["code"] == "security"


def _with_bearer(token: str) -> dict[str, str]:
    """Return an ``Authorization: Bearer`` header for *token*."""
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Property 13 — auth rejects every non-matching token
# ---------------------------------------------------------------------------


# Bearer header values must be transmittable ASCII (RFC 7235 token68 / visible
# ASCII); constrain the strategy so generated tokens are valid header values —
# the property under test is auth rejection, not HTTP header encoding.
_HEADER_SAFE = st.text(
    alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E),
    min_size=0,
    max_size=64,
)


# Feature: hr-pipeline, Property 13: Auth rejects every non-matching token
@settings(max_examples=150)
@given(bad_token=_HEADER_SAFE)
def test_property_auth_rejects_non_matching_tokens(bad_token: str) -> None:
    """Any token that is not the configured token yields a 401 security outcome.

    Validates: Requirements FR-12.1, FR-12.3, FR-12.4.
    """
    # Constrain the input space to genuinely non-matching tokens.
    if bad_token == _TOKEN:
        return
    app = _build_app()
    response = _run(_request(app, "/fhir/metadata", headers=_with_bearer(bad_token)))
    _assert_security_401(response)


# ---------------------------------------------------------------------------
# Example cases from the task
# ---------------------------------------------------------------------------


def test_missing_authorization_header_is_401() -> None:
    """A request with no ``Authorization`` header is rejected with 401.

    Validates: Requirements FR-12.1, FR-12.3, FR-12.4.
    """
    app = _build_app()
    response = _run(_request(app, "/fhir/metadata"))
    _assert_security_401(response)


def test_wrong_token_is_401() -> None:
    """A request with an incorrect bearer token is rejected with 401.

    Validates: Requirements FR-12.1, FR-12.3, FR-12.4.
    """
    app = _build_app()
    response = _run(_request(app, "/fhir/metadata", headers=_with_bearer("wrong-token")))
    _assert_security_401(response)


def test_correct_token_succeeds() -> None:
    """A request with the correct bearer token succeeds with FHIR content-type.

    Validates: Requirements FR-12.1, FR-12.3.
    """
    app = _build_app()
    response = _run(_request(app, "/fhir/metadata", headers=_with_bearer(_TOKEN)))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(_FHIR_MEDIA_TYPE)
    body = json.loads(response.content)
    assert body["resourceType"] == "CapabilityStatement"


def test_correct_token_unknown_id_is_404_not_401() -> None:
    """With a valid token, an unknown Observation id is a 404 not-found outcome.

    Confirms auth passes independently of resource existence: a good token plus
    a missing id returns 404 (issue code ``not-found``), not 401.

    Validates: Requirements FR-12.4.
    """
    app = _build_app()
    response = _run(
        _request(app, "/fhir/Observation/does-not-exist", headers=_with_bearer(_TOKEN))
    )
    assert response.status_code == 404
    assert response.headers["content-type"].startswith(_FHIR_MEDIA_TYPE)
    body = json.loads(response.content)
    assert body["resourceType"] == "OperationOutcome"
    assert body["issue"][0]["code"] == "not-found"


def test_unknown_id_without_token_is_401() -> None:
    """Auth is enforced before resource lookup: no token on an unknown id is 401.

    Validates: Requirements FR-12.1, FR-12.4.
    """
    app = _build_app()
    response = _run(_request(app, "/fhir/Observation/does-not-exist"))
    _assert_security_401(response)
