# SPDX-License-Identifier: AGPL-3.0-or-later
"""Property tests for ``InMemoryObservationStore``.

This module is shared across store tasks 6.1 / 6.2 / 6.3; each task adds its own
distinctly named test functions. Shared helpers live at module scope and must
stay task-agnostic so sibling tasks can reuse them without clobbering.

- Property 10 (task 6.1): the store honors its ``max_size`` bound and evicts the
  oldest entries first, retaining the most-recently-added readings.
- Property 11 (task 6.2): reads return isolated deep-copied snapshots, so a caller
  mutating a returned resource cannot corrupt the store's internal state.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from vitals_on_fhir.fhir.mappers import ScalarVitalMapper
from vitals_on_fhir.store import InMemoryObservationStore
from vitals_on_fhir.vitals.builtin.heart_rate import HeartRate

_PATIENT_REF = "Patient/local-patient"
_DEVICE_REF = "Device/mock-hr"
_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


def _make_observation(*, value: float, seconds: int) -> object:
    """Build a valid FHIR Observation for a synthetic heart-rate reading.

    Uses the real ``ScalarVitalMapper`` so the Observation is a genuine
    ``fhir.resources`` model (the same type the store holds in production),
    keeping the isolation property meaningful.
    """
    reading = HeartRate(
        effective=_EPOCH + timedelta(seconds=seconds),
        device_id="mock-hr",
        value=value,
    )
    return ScalarVitalMapper().to_observation(
        reading,
        patient_ref=_PATIENT_REF,
        device_ref=_DEVICE_REF,
        issued=_EPOCH + timedelta(seconds=seconds),
    )


# Feature: hr-pipeline, Property 11: Store reads return isolated snapshots
# Validates: Requirements FR-STORE.4 (NFR — async snapshot reads)
@settings(max_examples=200)
@given(
    value=st.floats(min_value=20.0, max_value=250.0, allow_nan=False, allow_infinity=False),
    tampered=st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
)
def test_reads_return_isolated_snapshots(value: float, tampered: float) -> None:
    """Mutating a resource returned by the store never changes stored state.

    For any stored Observation, mutating the object handed back by ``get`` (or by
    ``search``) must not affect the store: a subsequent read returns the original
    value. This confirms reads return isolated deep-copied snapshots rather than
    live references to internal state.
    """

    async def scenario() -> None:
        store = InMemoryObservationStore(max_size=10)
        observation = _make_observation(value=value, seconds=0)
        original_value = observation.valueQuantity.value
        observation_id = observation.id
        await store.add(observation)

        # Mutate the copy returned by get(): must not touch internal state.
        got = await store.get(observation_id)
        assert got is not None
        assert got is not observation  # a distinct object, not a live reference
        got.valueQuantity.value = tampered
        got.status = "entered-in-error"

        reread = await store.get(observation_id)
        assert reread is not None
        assert reread.valueQuantity.value == original_value
        assert reread.status == "final"

        # Mutate a resource returned by search(): must not touch internal state.
        results = await store.search()
        assert len(results) == 1
        results[0].valueQuantity.value = tampered
        results[0].status = "cancelled"

        after_search = await store.get(observation_id)
        assert after_search is not None
        assert after_search.valueQuantity.value == original_value
        assert after_search.status == "final"

    asyncio.run(scenario())


# Feature: hr-pipeline, Property 10: Store never exceeds its bound and evicts oldest
# Validates: Requirements FR-STORE.2 (VOF_STORE_MAX bound + oldest eviction)
@settings(max_examples=150, deadline=None)
@given(
    max_size=st.integers(min_value=1, max_value=50),
    extra=st.integers(min_value=0, max_value=50),
)
def test_store_bound_and_eviction(max_size: int, extra: int) -> None:
    """A store bounded at M holds at most M and retains the newest M readings.

    After adding N = M + extra distinct Observations to a store bounded at M, the
    store never holds more than M entries, retains exactly the most-recently-added
    min(N, M) of them, and has evicted the oldest ones (oldest-first eviction).
    """
    total = max_size + extra

    async def scenario() -> None:
        store = InMemoryObservationStore(max_size=max_size)
        observations = [_make_observation(value=60.0 + (i % 30), seconds=i) for i in range(total)]
        ids_in_order = [obs.id for obs in observations]

        for obs in observations:
            await store.add(obs)

        expected_kept = min(total, max_size)
        expected_ids = set(ids_in_order[-expected_kept:])
        evicted_ids = set(ids_in_order[:-expected_kept]) if total > max_size else set()

        # Bound: the store never exceeds max_size.
        remaining = await store.search(count=None)
        assert len(remaining) <= max_size
        assert len(remaining) == expected_kept

        # Retention: the newest expected_kept ids are all present.
        for kept_id in expected_ids:
            assert await store.get(kept_id) is not None

        # Eviction: the oldest ids are gone.
        for gone_id in evicted_ids:
            assert await store.get(gone_id) is None

    asyncio.run(scenario())

# Feature: hr-pipeline, Property 12: Search results honor filters, sort, and count
# Validates: Requirements FR-STORE.4, FR-11
def test_fresh_store_searches_empty() -> None:
    """A freshly constructed store returns no results and a zero match count.

    Example test: with nothing added, ``search`` (with or without filters) yields
    an empty list, so the Bundle-equivalent ``total`` (the match count) is zero.
    """

    async def scenario() -> None:
        store = InMemoryObservationStore(max_size=10)

        assert await store.search() == []
        assert await store.search(count=5) == []
        assert await store.search(code="8867-4") == []
        assert (
            await store.search(
                date_from=_EPOCH,
                date_to=_EPOCH + timedelta(hours=1),
            )
            == []
        )

    asyncio.run(scenario())


def _observation_effective(observation: object) -> datetime:
    """Return the ``effectiveDateTime`` of an Observation as a comparable datetime."""
    effective = observation.effectiveDateTime  # type: ignore[attr-defined]
    if effective.tzinfo is None:
        return effective.replace(tzinfo=UTC)
    return effective


def _observation_code(observation: object) -> str:
    """Return the first LOINC coding ``code`` of an Observation."""
    return observation.code.coding[0].code  # type: ignore[attr-defined]


# Feature: hr-pipeline, Property 12: Search results honor filters, sort, and count
# Validates: Requirements FR-STORE.4, FR-11
@settings(max_examples=150, deadline=None)
@given(
    seconds=st.lists(
        st.integers(min_value=0, max_value=100_000),
        min_size=0,
        max_size=25,
        unique=True,
    ),
    window=st.tuples(
        st.integers(min_value=0, max_value=100_000),
        st.integers(min_value=0, max_value=100_000),
    ),
    use_code=st.booleans(),
    use_from=st.booleans(),
    use_to=st.booleans(),
    sort_desc=st.booleans(),
    count=st.one_of(st.none(), st.integers(min_value=0, max_value=30)),
)
def test_search_honors_filters_sort_and_count(
    seconds: list[int],
    window: tuple[int, int],
    use_code: bool,
    use_from: bool,
    use_to: bool,
    sort_desc: bool,
    count: int | None,
) -> None:
    """Search results respect every filter, the sort order, and the count bound.

    For any set of stored heart-rate Observations and any combination of ``code``,
    ``date_from``/``date_to`` bounds, ``sort_desc``, and ``count``:

    - every returned entry satisfies all supplied filters,
    - results are ordered by ``effectiveDateTime`` (descending when ``sort_desc``),
    - the number of entries is at most ``count`` when supplied,
    - the Bundle-equivalent total (the count of matches before truncation) equals
      the number of stored Observations that match the filters, and
    - the code filter selects only the requested LOINC code.
    """
    low, high = sorted(window)
    date_from = _EPOCH + timedelta(seconds=low) if use_from else None
    date_to = _EPOCH + timedelta(seconds=high) if use_to else None
    # HeartRate's LOINC code; every stored Observation carries it, so a code filter
    # of "8867-4" matches all and an unrelated code matches none.
    code = "8867-4" if use_code else None

    async def scenario() -> None:
        store = InMemoryObservationStore(max_size=1000)
        stored = [
            _make_observation(value=60.0 + (i % 30), seconds=s) for i, s in enumerate(seconds)
        ]
        for obs in stored:
            await store.add(obs)

        # Reference set: the matches computed independently of the store.
        expected = [
            obs
            for obs in stored
            if (code is None or _observation_code(obs) == code)
            and (date_from is None or _observation_effective(obs) >= date_from)
            and (date_to is None or _observation_effective(obs) <= date_to)
        ]

        results = await store.search(
            code=code,
            date_from=date_from,
            date_to=date_to,
            sort_desc=sort_desc,
            count=count,
        )

        # Count bound: never more than the requested page size.
        if count is not None:
            assert len(results) <= count

        # Bundle-equivalent total: the full (untruncated) match count is stable and
        # equal to the independently computed reference count.
        full = await store.search(
            code=code,
            date_from=date_from,
            date_to=date_to,
            sort_desc=sort_desc,
            count=None,
        )
        assert len(full) == len(expected)

        # The returned page is a prefix (by size) of the full match set.
        expected_page = len(expected) if count is None else min(count, len(expected))
        assert len(results) == expected_page

        # Every returned entry satisfies all supplied filters.
        for obs in results:
            if code is not None:
                assert _observation_code(obs) == code
            if date_from is not None:
                assert _observation_effective(obs) >= date_from
            if date_to is not None:
                assert _observation_effective(obs) <= date_to

        # Sort order: effectiveDateTime is monotonic in the requested direction.
        effectives = [_observation_effective(obs) for obs in results]
        if sort_desc:
            assert effectives == sorted(effectives, reverse=True)
        else:
            assert effectives == sorted(effectives)

    asyncio.run(scenario())
