# SPDX-License-Identifier: AGPL-3.0-or-later
"""Demo mode: the API and dashboard WebSocket with authentication switched off.

With an :class:`AnonymousAuthenticator` (no ``VOF_API_TOKEN``, mock adapter)
every request is accepted without a token; with a
:class:`StaticTokenAuthenticator` nothing changes.  ``GET /status`` is public
in both cases and tells the dashboard which of the two it is talking to.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from vitals_on_fhir.api.app import create_app
from vitals_on_fhir.api.auth import (
    AnonymousAuthenticator,
    Authenticator,
    StaticTokenAuthenticator,
)
from vitals_on_fhir.fhir import build_device, build_patient
from vitals_on_fhir.store import InMemoryObservationStore
from vitals_on_fhir.vitals.base import DeviceInfo

# Synthetic token — never a real credential (security-privacy.md).
_TOKEN = "test-token-do-not-use"


class _RecordingBroadcaster:
    """``BroadcasterLike`` that remembers how many sockets were registered."""

    def __init__(self) -> None:
        self.registered = 0

    async def register(self, websocket: object) -> None:
        """Count an accepted socket."""
        self.registered += 1

    async def unregister(self, websocket: object) -> None:
        """Drop a socket (nothing to undo)."""


def _build_app(authenticator: Authenticator, broadcaster: _RecordingBroadcaster) -> FastAPI:
    """Build the app with *authenticator*; no static files, empty store."""
    return create_app(
        store=InMemoryObservationStore(max_size=10),
        authenticator=authenticator,
        broadcaster=broadcaster,
        patient=build_patient("local-patient"),
        device=build_device(DeviceInfo(manufacturer="m", model="x", identifiers={"mock": "1"})),
    )


@pytest.mark.parametrize(
    ("authenticator", "expected"),
    [(AnonymousAuthenticator(), False), (StaticTokenAuthenticator(_TOKEN), True)],
)
def test_status_is_public_and_reports_whether_a_token_is_needed(
    authenticator: Authenticator, expected: bool
) -> None:
    """``GET /status`` needs no token and says whether the others do."""
    client = TestClient(_build_app(authenticator, _RecordingBroadcaster()))

    response = client.get("/status")

    assert response.status_code == 200
    assert response.json() == {"auth_required": expected}


@pytest.mark.parametrize(
    "path", ["/fhir/metadata", "/fhir/Observation", "/fhir/Patient/local-patient"]
)
def test_demo_mode_serves_fhir_without_a_token(path: str) -> None:
    """In demo mode the FHIR API answers requests that carry no token."""
    client = TestClient(_build_app(AnonymousAuthenticator(), _RecordingBroadcaster()))

    assert client.get(path).status_code == 200


def test_token_mode_still_rejects_a_missing_token() -> None:
    """With a configured token, a request without one is still a 401."""
    client = TestClient(_build_app(StaticTokenAuthenticator(_TOKEN), _RecordingBroadcaster()))

    assert client.get("/fhir/metadata").status_code == 401


def test_demo_mode_accepts_a_websocket_without_a_token() -> None:
    """The dashboard socket opens with no ``?token=`` in demo mode."""
    broadcaster = _RecordingBroadcaster()
    client = TestClient(_build_app(AnonymousAuthenticator(), broadcaster))

    with client.websocket_connect("/ws"):
        pass

    assert broadcaster.registered == 1


def test_token_mode_rejects_a_websocket_without_a_token() -> None:
    """With a configured token, a socket without one is closed with 1008."""
    broadcaster = _RecordingBroadcaster()
    client = TestClient(_build_app(StaticTokenAuthenticator(_TOKEN), broadcaster))

    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect("/ws"):
        pass

    assert exc_info.value.code == 1008
    assert broadcaster.registered == 0
