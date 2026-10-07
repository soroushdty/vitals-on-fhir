# SPDX-License-Identifier: AGPL-3.0-or-later
"""API tests for ``GET /fhir/Observation`` paging.

``Bundle.total`` is the number of Observations that match the search; ``_count``
only limits how many of them the page carries (FHIR R4 Bundle.total, search
``_count``). Driven through the ASGI app over an in-process
:class:`httpx.ASGITransport`; no live server is started.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from vitals_on_fhir.api.app import create_app
from vitals_on_fhir.api.auth import StaticTokenAuthenticator
from vitals_on_fhir.fhir import ScalarVitalMapper, build_device, build_patient
from vitals_on_fhir.store import InMemoryObservationStore
from vitals_on_fhir.vitals import BodyWeight, HeartRate
from vitals_on_fhir.vitals.base import DeviceInfo, VitalSign

# Synthetic token — never a real credential (security-privacy.md).
_TOKEN = "test-token-do-not-use"
_HR_LOINC = "8867-4"
_START = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)


class _FakeBroadcaster:
    """Minimal broadcaster satisfying ``BroadcasterLike`` for app construction."""

    async def register(self, websocket: object) -> None:
        """No-op registration."""

    async def unregister(self, websocket: object) -> None:
        """No-op unregistration."""


async def _search(readings: list[VitalSign], query: str) -> dict[str, Any]:
    """Store *readings* as Observations and return the searchset for *query*."""
    store = InMemoryObservationStore(max_size=100)
    mapper = ScalarVitalMapper()
    for reading in readings:
        await store.add(
            mapper.to_observation(reading, "Patient/local-patient", "Device/dev", issued=_START)
        )
    app = create_app(
        store=store,
        authenticator=StaticTokenAuthenticator(_TOKEN),
        broadcaster=_FakeBroadcaster(),
        patient=build_patient("local-patient"),
        device=build_device(DeviceInfo(manufacturer="Generic", model="Test", identifiers={})),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/fhir/Observation{query}", headers={"Authorization": f"Bearer {_TOKEN}"}
        )
    assert response.status_code == 200
    body: dict[str, Any] = json.loads(response.content)
    return body


def _heart_rates(n: int) -> list[VitalSign]:
    """Return *n* heart-rate readings one second apart."""
    return [
        HeartRate(effective=_START + timedelta(seconds=i), device_id="dev", value=70.0 + i)
        for i in range(n)
    ]


@pytest.mark.parametrize(
    ("query", "page_size"),
    [
        ("?_count=2", 2),
        ("?_count=0", 0),
        ("?_count=50", 5),
        ("", 5),
    ],
)
def test_total_counts_every_match_and_count_limits_the_page(query: str, page_size: int) -> None:
    """``total`` is 5 for 5 matches whatever ``_count`` is; the page holds at most ``_count``."""
    body = asyncio.run(_search(_heart_rates(5), query))

    assert body["total"] == 5
    assert len(body.get("entry", [])) == page_size


def test_count_keeps_the_newest_matches_first() -> None:
    """With ``_sort=-date&_count=2`` the page is the two newest readings."""
    body = asyncio.run(_search(_heart_rates(5), "?_sort=-date&_count=2"))

    values = [entry["resource"]["valueQuantity"]["value"] for entry in body["entry"]]
    assert values == [74.0, 73.0]
    assert body["total"] == 5


def test_total_counts_only_observations_matching_the_code() -> None:
    """Readings with another code are not counted in ``total``."""
    weight = BodyWeight(effective=_START, device_id="dev", value=70.0)
    body = asyncio.run(_search([*_heart_rates(3), weight], f"?code={_HR_LOINC}&_count=1"))

    assert body["total"] == 3
    assert len(body["entry"]) == 1
