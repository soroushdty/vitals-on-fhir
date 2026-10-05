# SPDX-License-Identifier: AGPL-3.0-or-later
"""API tests for the body-weight slice.

Exercises the read-only FHIR API through the ASGI app returned by
:func:`vitals_on_fhir.api.app.create_app`, driven by ``httpx.AsyncClient`` over
an in-process :class:`httpx.ASGITransport` — no live server is started (see
``testing.md`` "API authentication tests").

Confirms that body-weight Observations are searchable by their LOINC code
through the existing ``GET /fhir/Observation?code=29463-7`` endpoint with no new
endpoint, that the ``GET /fhir/metadata`` CapabilityStatement reflects
Observation searchability, and that the API exposes no write operation.

The weight Observations are produced by the reused ``ScalarVitalMapper`` from
``BodyWeight`` readings and added to an ``InMemoryObservationStore`` (no
hardware, no adapter needed for the API surface under test).

Validates: Requirements FR-WT-7, FR-WT-5, NFR-WT-3.
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
from vitals_on_fhir.vitals import BodyWeight, HeartRate
from vitals_on_fhir.vitals.base import DeviceInfo

if TYPE_CHECKING:
    from fastapi import FastAPI
    from fhir.resources.R4B.observation import Observation

# Synthetic token — never a real credential (security-privacy.md).
_TOKEN = "test-token-do-not-use"
_PATIENT_ID = "local-patient"
_FHIR_MEDIA_TYPE = "application/fhir+json"

_WEIGHT_LOINC = "29463-7"
_HR_LOINC = "8867-4"


class _FakeBroadcaster:
    """Minimal broadcaster satisfying ``BroadcasterLike`` for app construction."""

    async def register(self, websocket: object) -> None:
        """No-op registration."""

    async def unregister(self, websocket: object) -> None:
        """No-op unregistration."""


def _weight_observation(value: float) -> Observation:
    """Map a ``BodyWeight`` reading to a FHIR Observation via the scalar mapper."""
    reading = BodyWeight(
        effective=datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
        device_id="dev-weight",
        value=value,
    )
    return ScalarVitalMapper().to_observation(
        reading,
        f"Patient/{_PATIENT_ID}",
        "Device/weight-scale",
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
        model="Weight Scale",
        identifiers={"profile": "org.bluetooth.service.weight_scale"},
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
# Search by weight LOINC code
# ---------------------------------------------------------------------------


def test_search_by_weight_code_returns_weight_observations() -> None:
    """``GET /fhir/Observation?code=29463-7`` returns only weight Observations.

    A store holding both a body-weight and a heart-rate Observation, when
    searched by the weight LOINC code, yields a searchset Bundle whose entries
    are exactly the weight Observation(s) — the existing ``code`` search
    parameter filters them with no new endpoint (FR-WT-7).

    Validates: Requirements FR-WT-7, FR-WT-5, NFR-WT-3
    """
    store = InMemoryObservationStore(max_size=100)
    weight_obs = _weight_observation(70.0)
    hr_obs = _heart_rate_observation(72.0)

    async def scenario() -> httpx.Response:
        await store.add(weight_obs)
        await store.add(hr_obs)
        app = _build_app(store)
        return await _get(
            app, f"/fhir/Observation?code={_WEIGHT_LOINC}", headers=_auth()
        )

    response = _run(scenario())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(_FHIR_MEDIA_TYPE)
    body = json.loads(response.content)

    assert body["resourceType"] == "Bundle"
    assert body["type"] == "searchset"
    # Only the weight Observation matches the weight code.
    assert body["total"] == 1
    entries = body["entry"]
    assert len(entries) == 1
    resource = entries[0]["resource"]
    assert resource["resourceType"] == "Observation"
    assert resource["code"]["coding"][0]["code"] == _WEIGHT_LOINC
    assert resource["id"] == weight_obs.id


def test_search_by_system_and_weight_code_matches() -> None:
    """The ``system|code`` token form also filters weight Observations.

    ``code=http://loinc.org|29463-7`` yields the same weight Observation as the
    bare-code form, confirming the token parameter handles both shapes.

    Validates: Requirements FR-WT-7
    """
    store = InMemoryObservationStore(max_size=100)
    weight_obs = _weight_observation(82.4)

    async def scenario() -> httpx.Response:
        await store.add(weight_obs)
        app = _build_app(store)
        return await _get(
            app,
            f"/fhir/Observation?code=http://loinc.org|{_WEIGHT_LOINC}",
            headers=_auth(),
        )

    response = _run(scenario())

    assert response.status_code == 200
    body = json.loads(response.content)
    assert body["total"] == 1
    assert body["entry"][0]["resource"]["code"]["coding"][0]["code"] == _WEIGHT_LOINC


def test_search_by_weight_code_empty_when_none_stored() -> None:
    """Searching by the weight code returns an empty Bundle when none stored.

    With only a heart-rate Observation present, a weight-code search yields a
    searchset Bundle with ``total`` 0 and no entries — the code filter does not
    cross-match another vital's Observations.

    Validates: Requirements FR-WT-7
    """
    store = InMemoryObservationStore(max_size=100)
    hr_obs = _heart_rate_observation(72.0)

    async def scenario() -> httpx.Response:
        await store.add(hr_obs)
        app = _build_app(store)
        return await _get(
            app, f"/fhir/Observation?code={_WEIGHT_LOINC}", headers=_auth()
        )

    response = _run(scenario())

    assert response.status_code == 200
    body = json.loads(response.content)
    assert body["resourceType"] == "Bundle"
    assert body["type"] == "searchset"
    assert body["total"] == 0
    assert body.get("entry", []) == []


def test_get_weight_observation_by_id() -> None:
    """A stored weight Observation is retrievable by its logical id.

    Confirms the read interaction serves the same body-weight Observation that
    search surfaces, with the FHIR media type.

    Validates: Requirements FR-WT-7, FR-WT-5
    """
    store = InMemoryObservationStore(max_size=100)
    weight_obs = _weight_observation(66.6)

    async def scenario() -> httpx.Response:
        await store.add(weight_obs)
        app = _build_app(store)
        return await _get(app, f"/fhir/Observation/{weight_obs.id}", headers=_auth())

    response = _run(scenario())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(_FHIR_MEDIA_TYPE)
    body = json.loads(response.content)
    assert body["resourceType"] == "Observation"
    assert body["id"] == weight_obs.id
    assert body["code"]["coding"][0]["code"] == _WEIGHT_LOINC


# ---------------------------------------------------------------------------
# CapabilityStatement reflects searchability
# ---------------------------------------------------------------------------


def test_capability_statement_reflects_observation_searchability() -> None:
    """``GET /fhir/metadata`` advertises Observation search by ``code``.

    Body-weight Observations are searchable through the same read-only endpoints
    as every other vital, so the CapabilityStatement must advertise the
    Observation resource with a ``search-type`` interaction and a ``code`` token
    search parameter (the endpoint set and parameters are code-generic — no
    weight-specific endpoint is added).

    Validates: Requirements FR-WT-7
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
    code_param = next(p for p in observation["searchParam"] if p["name"] == "code")
    assert code_param["type"] == "token"


# ---------------------------------------------------------------------------
# No write operation
# ---------------------------------------------------------------------------


def test_capability_statement_advertises_no_write_interaction() -> None:
    """The CapabilityStatement advertises only read/search interactions.

    No ``create``, ``update``, ``patch``, or ``delete`` interaction appears on
    any resource — the API is read-only (FR-WT-7).

    Validates: Requirements FR-WT-7
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


def test_post_weight_observation_is_rejected() -> None:
    """A write attempt against the Observation endpoint is not accepted.

    The API defines no write route, so a ``POST`` to ``/fhir/Observation`` must
    not create a resource — FastAPI returns 405 Method Not Allowed for the
    unrouted method (never a 2xx success).

    Validates: Requirements FR-WT-7
    """
    store = InMemoryObservationStore(max_size=100)
    app = _build_app(store)

    response = _run(_request(app, "POST", "/fhir/Observation", headers=_auth()))

    assert response.status_code == 405
