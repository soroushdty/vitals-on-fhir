# SPDX-License-Identifier: AGPL-3.0-or-later
"""API token-leak property test (task 9.5).

Exercises the read-only FHIR API through the ASGI app returned by
:func:`vitals_on_fhir.api.app.create_app`, driven by ``httpx.AsyncClient`` over
an in-process :class:`httpx.ASGITransport` — no live server is ever started
(see ``testing.md`` "API authentication tests"). Reuses the app-building,
``_run`` / ``_request`` helpers, and ``_FakeBroadcaster`` patterns from
``test_auth.py``.

Covers **Property 14: The token never leaks** — for valid *and* invalid
requests across every endpoint, the configured ``VOF_API_TOKEN`` value never
appears in the response body, in any response header value, or in any captured
log record at any level (``caplog`` set to ``DEBUG`` to capture all levels).

Validates: Requirements FR-12.5, NFR-5.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from typing import TYPE_CHECKING

import httpx
import pytest
from hypothesis import HealthCheck, given, settings
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

# Read-only endpoints exercised by the property; a mix of collection, item,
# and singleton routes so both success and not-found paths are covered.
_PATHS: tuple[str, ...] = (
    "/fhir/metadata",
    "/fhir/Observation",
    "/fhir/Observation/does-not-exist",
    f"/fhir/Patient/{_PATIENT_ID}",
    "/fhir/Patient/unknown",
    "/fhir/Device/unknown",
)


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


def _assert_token_absent(response: httpx.Response, caplog: pytest.LogCaptureFixture) -> None:
    """Assert the configured token appears in no observable output."""
    # Body: the token must never be echoed back to the client.
    assert _TOKEN not in response.text
    assert _TOKEN.encode() not in response.content

    # Headers: neither names nor values may carry the token.
    for name, value in response.headers.items():
        assert _TOKEN not in name
        assert _TOKEN not in value

    # Logs: no record at any level (caplog captures DEBUG and above) may carry
    # the token, in its formatted message or its raw args.
    for record in caplog.records:
        assert _TOKEN not in record.getMessage()
        assert _TOKEN not in str(record.args or "")


# ---------------------------------------------------------------------------
# Property 14 — the token never leaks
# ---------------------------------------------------------------------------


# Auth header shapes: the correct bearer token, an incorrect one, a malformed
# scheme, and no header at all — so both authenticated and rejected paths run.
_HEADER_STRATEGY = st.sampled_from(
    (
        {"Authorization": f"Bearer {_TOKEN}"},
        {"Authorization": "Bearer wrong-token"},
        {"Authorization": _TOKEN},  # missing "Bearer " scheme
        {},
    )
)


# Feature: hr-pipeline, Property 14: The token never leaks
@settings(max_examples=150, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(path=st.sampled_from(_PATHS), headers=_HEADER_STRATEGY)
def test_property_token_never_leaks(
    path: str,
    headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The configured token never appears in the body, headers, or logs.

    Holds for valid requests (correct bearer token) and invalid ones (wrong
    token, malformed scheme, or no header) across every read-only endpoint.

    Validates: Requirements FR-12.5, NFR-5.
    """
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        app = _build_app()
        response = _run(_request(app, path, headers=headers or None))
    _assert_token_absent(response, caplog)
