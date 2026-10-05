# SPDX-License-Identifier: AGPL-3.0-or-later
"""The dashboard's static files must be revalidated by browsers on every load.

Without ``Cache-Control`` browsers apply heuristic caching and keep showing an
old dashboard after an upgrade, without ever contacting the server.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from vitals_on_fhir.api.app import create_app
from vitals_on_fhir.api.auth import StaticTokenAuthenticator
from vitals_on_fhir.fhir import build_device, build_patient
from vitals_on_fhir.store import InMemoryObservationStore
from vitals_on_fhir.vitals.base import DeviceInfo


class _FakeBroadcaster:
    """Minimal ``BroadcasterLike``; the WebSocket route is not exercised here."""

    async def register(self, websocket: object) -> None:
        """Accept a socket (unused)."""

    async def unregister(self, websocket: object) -> None:
        """Drop a socket (unused)."""


def test_static_files_are_served_with_no_cache(tmp_path: Path) -> None:
    """Both the index page and assets carry ``Cache-Control: no-cache``."""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "app.js").write_text("// js", encoding="utf-8")
    app = create_app(
        store=InMemoryObservationStore(10),
        authenticator=StaticTokenAuthenticator("test-token-do-not-use"),
        broadcaster=_FakeBroadcaster(),
        patient=build_patient("local-patient"),
        device=build_device(DeviceInfo(manufacturer="m", model="x", identifiers={"mock": "1"})),
        static_dir=tmp_path,
    )

    async def fetch(path: str) -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)

    for path in ("/", "/app.js"):
        response = asyncio.run(fetch(path))
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache"
