# SPDX-License-Identifier: AGPL-3.0-or-later
"""API tests for the body-temperature slice (task 8.2).

Exercises the read-only FHIR API through the ASGI app returned by
:func:`vitals_on_fhir.api.app.create_app`, driven by ``httpx.AsyncClient`` over
an in-process :class:`httpx.ASGITransport` — no live server is started (see
``testing.md`` "API authentication tests").

Confirms that body-temperature Observations are searchable by their LOINC code
through the existing ``GET /fhir/Observation?code=8310-5`` endpoint with no new
endpoint, that the ``GET /fhir/metadata`` CapabilityStatement reflects
Observation searchability (``search-type`` interaction and a ``code`` token
search parameter), and that the API exposes no write operation.

The temperature Observations are produced by the reused ``ScalarVitalMapper``
from ``BodyTemperature`` readings and added to an ``InMemoryObservationStore``
(no hardware, no adapter needed for the API surface under test).

Validates: Requirements FR-TEMP-7, FR-TEMP-5, NFR-TEMP-3.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx

from vitals_on_fhir.api.app import create_app
from vitals_on_fhir.api.auth import StaticTokenAuthenticator
from vitals_on_fhir.fhir import ScalarVitalMapper, build_device, build_patient
from vitals_on_fhir.store import InMemoryObservationStore
from vitals_on_fhir.vitals import BodyTemperature, HeartRate
from vitals_on_fhir.vitals.base import DeviceInfo

if TYPE_CHECKING:
    from fastapi import FastAPI
    from fhir.resources.R4B.observation import Observation

# Synthetic token — never a real credential (security-privacy.md).
_TOKEN = "test-token-do-not-use"
_PATIENT_ID = "local-patient"
_FHIR_MEDIA_TYPE = "application/fhir+json"

_TEMP_LOINC = "8310-5"
_HR_LOINC = "8867-4"


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


def _temperature_observation(value: float) -> Observation:
    """Map a ``BodyTemperature`` reading to a FHIR Observation via the scalar mapper."""
    reading = BodyTemperature(
        effective=datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
        device_id="dev-temp",
        value=value,
    )
    return ScalarVitalMapper().to_observation(
        reading,
        f"Patient/{_PATIENT_ID}",
        "Device/health-thermometer",
        issued=datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
    )


def _heart_rate_observation(value: float) -> Observation:
    """Map a ``HeartRate`` reading to a FHIR Observation via the scalar mapper."""
    reading = HeartRate(
        effective=datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
        device_id="dev-hr",
        value=value,
    )
    return ScalarVitalMapper().to_observation(
        reading,
        f"Patient/{_PATIENT_ID}",
        "Device/mock-hr",
        issued=datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
    )


def _build_app(store: InMemoryObservationStore) -> FastAPI:
    """Build a fully wired app with a synthetic token and the given store."""
    device_info = DeviceInfo(
        manufacturer="Generic",
        model="Health Thermometer",
        identifiers={"profile": "org.bluetooth.service.health_thermometer"},
    )
    return create_app(
        store=store,
        authenticator=StaticTokenAuthenticator(_TOKEN),
        broadcaster=_FakeBroadcaster(),
        patient=build_patient(_PATIENT_ID),
        device=build_device(device_info),
    )


def _run[T](coro: Awaitable[T]) -> T:
    """Run *coro* to completion on a fresh event loop (no live server)."""
    return asyncio.run(coro)  # type: ignore[arg-type]


async def _get(
    app: FastAPI,
    path: str,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Issue a GET against *app* over an in-process ASGI transport."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers)


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Issue an arbitrary-method request against *app* over an ASGI transport."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers)


def _auth() -> dict[str, str]:
    """Return the ``Authorization: Bearer`` header for the configured token."""
    return {"Authorization": f"Bearer {_TOKEN}"}


# ---------------------------------------------------------------------------
# Search by temperature LOINC code
# ---------------------------------------------------------------------------


def test_search_by_temperature_code_returns_temperature_observations() -> None:
    """``GET /fhir/Observation?code=8310-5`` returns only temperature Observations.

    A store holding both a body-temperature and a heart-rate Observation, when
    searched by the temperature LOINC code, yields a searchset Bundle whose
    entries are exactly the temperature Observation(s) — the existing ``code``
    search parameter filters them with no new endpoint (FR-TEMP-7).

    Validates: Requirements FR-TEMP-7, FR-TEMP-5, NFR-TEMP-3
    """
    store = InMemoryObservationStore(max_size=100)
    temp_obs = _temperature_observation(37.0)
    hr_obs = _heart_rate_observation(72.0)

    async def scenario() -> httpx.Response:
        await store.add(temp_obs)
        await store.add(hr_obs)
        app = _build_app(store)
        return await _get(
            app, f"/fhir/Observation?code={_TEMP_LOINC}", headers=_auth()
        )

    response = _run(scenario())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(_FHIR_MEDIA_TYPE)
    body = json.loads(response.content)

    assert body["resourceType"] == "Bundle"
    assert body["type"] == "searchset"
    # Only the temperature Observation matches the temperature code.
    assert body["total"] == 1
    entries = body["entry"]
    assert len(entries) == 1
    resource = entries[0]["resource"]
    assert resource["resourceType"] == "Observation"
    assert resource["code"]["coding"][0]["code"] == _TEMP_LOINC
    assert resource["id"] == temp_obs.id


def test_search_by_system_and_temperature_code_matches() -> None:
    """The ``system|code`` token form also filters temperature Observations.

    ``code=http://loinc.org|8310-5`` yields the same temperature Observation as
    the bare-code form, confirming the token parameter handles both shapes.

    Validates: Requirements FR-TEMP-7
    """
    store = InMemoryObservationStore(max_size=100)
    temp_obs = _temperature_observation(38.5)

    async def scenario() -> httpx.Response:
        await store.add(temp_obs)
        app = _build_app(store)
        return await _get(
            app,
            f"/fhir/Observation?code=http://loinc.org|{_TEMP_LOINC}",
            headers=_auth(),
        )

    response = _run(scenario())

    assert response.status_code == 200
    body = json.loads(response.content)
    assert body["total"] == 1
    assert body["entry"][0]["resource"]["code"]["coding"][0]["code"] == _TEMP_LOINC


def test_search_by_temperature_code_empty_when_none_stored() -> None:
    """Searching by the temperature code returns an empty Bundle when none stored.

    With only a heart-rate Observation present, a temperature-code search yields
    a searchset Bundle with ``total`` 0 and no entries — the code filter does
    not cross-match another vital's Observations.

    Validates: Requirements FR-TEMP-7
    """
    store = InMemoryObservationStore(max_size=100)
    hr_obs = _heart_rate_observation(72.0)

    async def scenario() -> httpx.Response:
        await store.add(hr_obs)
        app = _build_app(store)
        return await _get(
            app, f"/fhir/Observation?code={_TEMP_LOINC}", headers=_auth()
        )

    response = _run(scenario())

    assert response.status_code == 200
    body = json.loads(response.content)
    assert body["resourceType"] == "Bundle"
    assert body["type"] == "searchset"
    assert body["total"] == 0
    assert body.get("entry", []) == []


def test_get_temperature_observation_by_id() -> None:
    """A stored temperature Observation is retrievable by its logical id.

    Confirms the read interaction serves the same body-temperature Observation
    that search surfaces, with the FHIR media type.

    Validates: Requirements FR-TEMP-7, FR-TEMP-5
    """
    store = InMemoryObservationStore(max_size=100)
    temp_obs = _temperature_observation(36.6)

    async def scenario() -> httpx.Response:
        await store.add(temp_obs)
        app = _build_app(store)
        return await _get(
            app, f"/fhir/Observation/{temp_obs.id}", headers=_auth()
        )

    response = _run(scenario())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(_FHIR_MEDIA_TYPE)
    body = json.loads(response.content)
    assert body["resourceType"] == "Observation"
    assert body["id"] == temp_obs.id
    assert body["code"]["coding"][0]["code"] == _TEMP_LOINC


# ---------------------------------------------------------------------------
# CapabilityStatement reflects searchability
# ---------------------------------------------------------------------------


def test_capability_statement_reflects_observation_searchability() -> None:
    """``GET /fhir/metadata`` advertises Observation search by ``code``.

    Body-temperature Observations are searchable through the same read-only
    endpoints as every other vital, so the CapabilityStatement must advertise
    the Observation resource with a ``search-type`` interaction and a ``code``
    token search parameter (the endpoint set and parameters are code-generic —
    no temperature-specific endpoint is added).

    Validates: Requirements FR-TEMP-7
    """
    store = InMemoryObservationStore(max_size=100)
    app = _build_app(store)

    response = _run(_get(app, "/fhir/metadata", headers=_auth()))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(_FHIR_MEDIA_TYPE)
    body = json.loads(response.content)
    assert body["resourceType"] == "CapabilityStatement"

    resources = body["rest"][0]["resource"]
    observation = next(r for r in resources if r["type"] == "Observation")

    interaction_codes = {i["code"] for i in observation["interaction"]}
    assert "search-type" in interaction_codes
    assert "read" in interaction_codes

    search_param_names = {p["name"] for p in observation["searchParam"]}
    assert "code" in search_param_names
    code_param = next(
        p for p in observation["searchParam"] if p["name"] == "code"
    )
    assert code_param["type"] == "token"


# ---------------------------------------------------------------------------
# No write operation
# ---------------------------------------------------------------------------


def test_capability_statement_advertises_no_write_interaction() -> None:
    """The CapabilityStatement advertises only read/search interactions.

    No ``create``, ``update``, ``patch``, or ``delete`` interaction appears on
    any resource — the API is read-only (FR-TEMP-7).

    Validates: Requirements FR-TEMP-7
    """
    store = InMemoryObservationStore(max_size=100)
    app = _build_app(store)

    response = _run(_get(app, "/fhir/metadata", headers=_auth()))
    body = json.loads(response.content)

    write_codes = {"create", "update", "patch", "delete"}
    for resource in body["rest"][0]["resource"]:
        codes = {i["code"] for i in resource.get("interaction", [])}
        assert codes.isdisjoint(write_codes), (
            f"{resource['type']} advertises a write interaction"
        )


def test_post_temperature_observation_is_rejected() -> None:
    """A write attempt against the Observation endpoint is not accepted.

    The API defines no write route, so a ``POST`` to ``/fhir/Observation`` must
    not create a resource — FastAPI returns 405 Method Not Allowed for the
    unrouted method (never a 2xx success).

    Validates: Requirements FR-TEMP-7
    """
    store = InMemoryObservationStore(max_size=100)
    app = _build_app(store)

    response = _run(
        _request(app, "POST", "/fhir/Observation", headers=_auth())
    )

    assert response.status_code == 405
    assert response.status_code < 200 or response.status_code >= 300
