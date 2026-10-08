# SPDX-License-Identifier: AGPL-3.0-or-later
"""API tests for the ``code`` and ``date`` search parameters of ``GET /fhir/Observation``.

``code`` is a FHIR token (``code``, ``system|code``, ``|code``, ``system|``), so a
given system must match too (#37). ``date`` covers the range its precision
implies and its prefix compares that range with ``effectiveDateTime``; an
invalid value is a 400, never an unfiltered search or a crash (#36). Driven
through the ASGI app over an in-process :class:`httpx.ASGITransport`.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

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

#: Heart-rate readings at these instants; each value identifies its reading.
_READINGS: dict[float, datetime] = {
    60.0: datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC),
    61.0: datetime(2026, 10, 7, 0, 0, 0, tzinfo=UTC),
    62.0: datetime(2026, 10, 7, 12, 0, 0, tzinfo=UTC),
    63.0: datetime(2026, 10, 7, 12, 0, 0, 500_000, tzinfo=UTC),
    64.0: datetime(2026, 10, 7, 23, 59, 59, tzinfo=UTC),
    65.0: datetime(2026, 10, 8, 0, 0, 0, tzinfo=UTC),
    66.0: datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC),
}


class _FakeBroadcaster:
    """Minimal broadcaster satisfying ``BroadcasterLike`` for app construction."""

    async def register(self, websocket: object) -> None:
        """No-op registration."""

    async def unregister(self, websocket: object) -> None:
        """No-op unregistration."""


def _heart_rates() -> list[VitalSign]:
    return [
        HeartRate(effective=effective, device_id="dev", value=value)
        for value, effective in _READINGS.items()
    ]


async def _get(
    readings: list[VitalSign], query: str, search_timezone: tzinfo | None = UTC
) -> httpx.Response:
    """Store *readings* as Observations and return the response to *query*."""
    store = InMemoryObservationStore(max_size=100)
    mapper = ScalarVitalMapper()
    issued = datetime(2027, 6, 1, tzinfo=UTC)
    for reading in readings:
        await store.add(
            mapper.to_observation(reading, "Patient/local-patient", "Device/dev", issued=issued)
        )
    app = create_app(
        store=store,
        authenticator=StaticTokenAuthenticator(_TOKEN),
        broadcaster=_FakeBroadcaster(),
        patient=build_patient("local-patient"),
        device=build_device(DeviceInfo(manufacturer="Generic", model="Test", identifiers={})),
        search_timezone=search_timezone,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(
            f"/fhir/Observation{query}", headers={"Authorization": f"Bearer {_TOKEN}"}
        )


def _values(
    query: str,
    readings: list[VitalSign] | None = None,
    search_timezone: tzinfo | None = UTC,
) -> list[float]:
    """Return the matching readings' values for *query*, oldest first."""
    response = asyncio.run(
        _get(_heart_rates() if readings is None else readings, query, search_timezone)
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = json.loads(response.content)
    return sorted(entry["resource"]["valueQuantity"]["value"] for entry in body.get("entry", []))


# ---------------------------------------------------------------------------
# code (#37)
# ---------------------------------------------------------------------------


def _hr_and_weight() -> list[VitalSign]:
    effective = datetime(2026, 10, 7, tzinfo=UTC)
    return [
        HeartRate(effective=effective, device_id="dev", value=70.0),
        BodyWeight(effective=effective + timedelta(seconds=1), device_id="dev", value=80.0),
    ]


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (_HR_LOINC, [70.0]),
        (f"http://loinc.org|{_HR_LOINC}", [70.0]),
        (f"http://snomed.info/sct|{_HR_LOINC}", []),
        (f"|{_HR_LOINC}", []),
        ("http://loinc.org|", [70.0, 80.0]),
        ("http://snomed.info/sct|", []),
    ],
)
def test_code_matches_the_system_as_well_as_the_code(code: str, expected: list[float]) -> None:
    """A system in the token must match the coding's system (FHIR token search)."""
    assert _values(f"?code={quote(code, safe='')}", _hr_and_weight()) == expected


# ---------------------------------------------------------------------------
# date (#36)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("date", "expected"),
    [
        # Precision sets the range a value covers.
        ("2026", [60.0, 61.0, 62.0, 63.0, 64.0, 65.0]),
        ("2026-10", [61.0, 62.0, 63.0, 64.0, 65.0]),
        ("2026-10-07", [61.0, 62.0, 63.0, 64.0]),
        ("eq2026-10-07", [61.0, 62.0, 63.0, 64.0]),
        ("2026-10-07T12:00", [62.0, 63.0]),
        ("2026-10-07T12:00:00Z", [62.0, 63.0]),
        ("2026-10-07T12:00:00.5Z", [63.0]),
        ("2026-10-07T12:00:00.000Z", [62.0]),
        # Prefixes compare the value's range with the instant.
        ("ge2026-10-07", [61.0, 62.0, 63.0, 64.0, 65.0, 66.0]),
        ("gt2026-10-07", [65.0, 66.0]),
        ("le2026-10-07", [60.0, 61.0, 62.0, 63.0, 64.0]),
        ("lt2026-10-07", [60.0]),
        ("gt2026-10-07T12:00:00Z", [64.0, 65.0, 66.0]),
        ("lt2026-10-07T12:00:00Z", [60.0, 61.0]),
        # A UTC offset shifts the range: 14:00+02:00 is 12:00Z.
        ("2026-10-07T14:00:00+02:00", [62.0, 63.0]),
        # December rolls into the next year.
        ("2026-12", []),
        ("lt2027-01", [60.0, 61.0, 62.0, 63.0, 64.0, 65.0]),
    ],
)
def test_date_covers_the_range_its_precision_implies(date: str, expected: list[float]) -> None:
    """``date`` follows FHIR date search, including values without a timezone."""
    assert _values(f"?date={quote(date, safe='')}") == expected


def test_a_value_without_a_timezone_is_read_as_utc_and_does_not_crash() -> None:
    """``ge2026-10-07T12:00:00`` used to raise a naive/aware ``TypeError`` (a 500)."""
    assert _values("?date=ge2026-10-07T12:00:00") == [62.0, 63.0, 64.0, 65.0, 66.0]


@pytest.mark.parametrize(
    ("date", "expected"),
    [
        # 2026-10-07 in Phoenix (UTC-7) is 07:00Z on the 7th to 07:00Z on the 8th.
        ("2026-10-07", [62.0, 63.0, 64.0, 65.0]),
        ("2026-10-07T05:00:00", [62.0, 63.0]),
        # An explicit offset is not affected by the setting.
        ("2026-10-07T12:00:00Z", [62.0, 63.0]),
    ],
)
def test_a_value_without_an_offset_is_in_the_search_timezone(
    date: str, expected: list[float]
) -> None:
    """``VOF_SEARCH_TIMEZONE`` sets the zone of a value without a UTC offset."""
    assert _values(f"?date={date}", search_timezone=ZoneInfo("America/Phoenix")) == expected


def test_a_day_is_midnight_to_midnight_across_a_dst_change() -> None:
    """In Berlin, 2026-10-25 lasts 25 hours: 22:00Z on the 24th to 23:00Z on the 25th."""
    readings: list[VitalSign] = [
        HeartRate(
            effective=datetime(2026, 10, 24, 21, 59, 59, tzinfo=UTC), device_id="d", value=1.0
        ),
        HeartRate(effective=datetime(2026, 10, 24, 22, 0, 0, tzinfo=UTC), device_id="d", value=2.0),
        HeartRate(
            effective=datetime(2026, 10, 25, 22, 59, 59, tzinfo=UTC), device_id="d", value=3.0
        ),
        HeartRate(effective=datetime(2026, 10, 25, 23, 0, 0, tzinfo=UTC), device_id="d", value=4.0),
    ]

    assert _values("?date=2026-10-25", readings, ZoneInfo("Europe/Berlin")) == [2.0, 3.0]


def test_local_uses_the_host_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    """``local`` (``None``) reads a value without an offset in the host's zone."""
    monkeypatch.setenv("TZ", "America/Phoenix")
    time.tzset()
    try:
        assert _values("?date=2026-10-07", search_timezone=None) == [62.0, 63.0, 64.0, 65.0]
    finally:
        monkeypatch.undo()
        time.tzset()


def test_an_unencoded_plus_in_the_offset_is_accepted() -> None:
    """``+02:00`` sent unencoded arrives as `` 02:00``; it is read as ``+02:00``."""
    assert _values("?date=2026-10-07T14:00:00+02:00") == [62.0, 63.0]


def test_repeated_dates_are_all_applied() -> None:
    """``date=ge…&date=lt…`` is a range: both bounds apply."""
    assert _values("?date=ge2026-10-07T12:00:00Z&date=lt2026-10-08") == [62.0, 63.0, 64.0]


@pytest.mark.parametrize(
    "date",
    [
        "garbage",
        "2026-13",
        "2026-02-30",
        "2026-10-07T25:00",
        "07-10-2026",
        "2026-10-07T12:00:00+25:00",
        "xx2026-10-07",
        "ge",
        "9999",
    ],
)
def test_an_invalid_date_is_a_400(date: str) -> None:
    """An unusable value returns an OperationOutcome, not an unfiltered search."""
    response = asyncio.run(_get(_heart_rates(), f"?date={date}"))

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/fhir+json")
    issue = json.loads(response.content)["issue"][0]
    assert issue["code"] == "invalid"


@pytest.mark.parametrize("prefix", ["ne", "sa", "eb", "ap"])
def test_an_unsupported_prefix_is_a_400(prefix: str) -> None:
    """Valid FHIR prefixes this server does not implement are reported, not ignored."""
    response = asyncio.run(_get(_heart_rates(), f"?date={prefix}2026-10-07"))

    assert response.status_code == 400
    assert json.loads(response.content)["issue"][0]["code"] == "not-supported"
