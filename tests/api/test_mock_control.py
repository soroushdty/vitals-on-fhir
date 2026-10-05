# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ``/mock/*`` scenario endpoints: auth, listing, switching, and absence."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from vitals_on_fhir.adapters import HeartRateScenario, HeartRateScenarioControl, MockAdapter
from vitals_on_fhir.api.app import create_app
from vitals_on_fhir.api.auth import StaticTokenAuthenticator
from vitals_on_fhir.fhir import build_device, build_patient
from vitals_on_fhir.store import InMemoryObservationStore
from vitals_on_fhir.vitals.base import DeviceInfo

_TOKEN = "test-token-do-not-use"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


class _FakeBroadcaster:
    """Minimal ``BroadcasterLike``; the WebSocket route is not exercised here."""

    async def register(self, websocket: object) -> None:
        """Accept a socket (unused)."""

    async def unregister(self, websocket: object) -> None:
        """Drop a socket (unused)."""


def _request(
    adapter: MockAdapter | None, method: str, path: str, **kwargs: object
) -> httpx.Response:
    """Send one request to an app built with (or without) a scenario control."""
    app = create_app(
        store=InMemoryObservationStore(10),
        authenticator=StaticTokenAuthenticator(_TOKEN),
        broadcaster=_FakeBroadcaster(),
        patient=build_patient("local-patient"),
        device=build_device(DeviceInfo(manufacturer="m", model="x", identifiers={"mock": "1"})),
        scenario_control=HeartRateScenarioControl(adapter) if adapter is not None else None,
    )

    async def go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)  # type: ignore[arg-type]

    return asyncio.run(go())


def test_lists_scenarios_and_the_active_one() -> None:
    """GET returns every scenario with label and description, plus the current id."""
    response = _request(MockAdapter(), "GET", "/mock/scenarios", headers=_AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["current"] == "normal_sinus_rhythm"
    assert [s["id"] for s in body["scenarios"]] == [s.value for s in HeartRateScenario]
    assert {"id", "label", "description"} == set(body["scenarios"][0])


def test_put_switches_the_adapter_scenario() -> None:
    """PUT applies the chosen scenario to the adapter and echoes it back."""
    adapter = MockAdapter()

    response = _request(
        adapter, "PUT", "/mock/scenario", headers=_AUTH, json={"scenario": "atrial_fibrillation"}
    )

    assert response.status_code == 200
    assert response.json() == {"current": "atrial_fibrillation"}
    assert adapter.scenario is HeartRateScenario.ATRIAL_FIBRILLATION


def test_put_unknown_scenario_is_a_400() -> None:
    """An unknown id is rejected and the scenario is left alone."""
    adapter = MockAdapter(scenario=HeartRateScenario.SINUS_BRADYCARDIA)

    response = _request(
        adapter, "PUT", "/mock/scenario", headers=_AUTH, json={"scenario": "nonsense"}
    )

    assert response.status_code == 400
    assert adapter.scenario is HeartRateScenario.SINUS_BRADYCARDIA


def test_requires_the_token() -> None:
    """Without a valid bearer token neither endpoint works, and nothing changes."""
    adapter = MockAdapter()

    for headers in ({}, {"Authorization": "Bearer wrong"}):
        assert _request(adapter, "GET", "/mock/scenarios", headers=headers).status_code == 401
        put = _request(
            adapter,
            "PUT",
            "/mock/scenario",
            headers=headers,
            json={"scenario": "sinus_tachycardia"},
        )
        assert put.status_code == 401

    assert adapter.scenario is HeartRateScenario.NORMAL_SINUS_RHYTHM


def test_endpoints_do_not_exist_without_a_control(tmp_path: Path) -> None:
    """With a non-mock adapter there is no control, so the paths are 404."""
    assert _request(None, "GET", "/mock/scenarios", headers=_AUTH).status_code == 404
    assert (
        _request(None, "PUT", "/mock/scenario", headers=_AUTH, json={"scenario": "x"}).status_code
        == 404
    )
