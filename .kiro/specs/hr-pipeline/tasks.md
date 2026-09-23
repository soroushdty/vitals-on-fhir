# Implementation Plan: hr-pipeline

## Overview

This plan fills in the business logic behind the `repo-scaffold` stubs so the heart-rate MVP works
end to end. Tasks edit existing stub modules and existing placeholder test files rather than
creating the package tree, and create the new helper modules the design calls for (parser payload
fixtures, the reusable `DeviceAdapter` contract suite, a `docs/` protocol citation). They are
ordered so the project stays green — `uv run ruff check .`, `uv run mypy src`, and the fast
`uv run pytest` suite — at each step, building from the leaf/domain layers outward per the
`structure.md` dependency-direction rules.

Cross-cutting constraints apply to every task that adds or edits a source file and are not repeated
as separate tasks:

- Every new/edited source file begins with `# SPDX-License-Identifier: AGPL-3.0-or-later`.
- `bleak` is imported lazily inside BLE adapter method bodies only — never at module level, never in
  `MockAdapter`, never in a non-`hardware` test.
- `fhir.resources` models are constructed directly, never subclassed or wrapped; serialization is
  `model_dump_json()` and validation is construction-time / `model_validate()`.
- The whole path is `async`; the store is guarded by an `asyncio.Lock` and returns copies;
  `asyncio.run()` appears only in `cli.py`.
- Token comparison is constant-time (`hmac.compare_digest`); auth failure is HTTP 401 (never 403)
  with an `OperationOutcome` (issue code `security`); the server binds `127.0.0.1` by default.
- No secrets (`VOF_API_TOKEN`) at any log level; no measurement values in logs at `INFO` or above.
- Property-based tests use Hypothesis at ≥100 iterations, each tagged with a comment
  `# Feature: hr-pipeline, Property N: <text>` referencing the design property number.
- The existing `tests/test_dependency_directions.py` must keep passing after every task.

## Tasks

- [x] 1. Implement the Heart Rate Measurement parser and its pure decoding functions
  - In `adapters/parser.py`, implement module-level pure functions `parse_flags`, `hr_value_size`,
    `required_length`, `decode_hr_value`, `decode_sensor_contact`, plus the internal `HrFlags`
    record (frozen dataclass / `NamedTuple`, not exported), per design §2 flags-byte table.
  - Implement `HeartRateMeasurementParser.parse(data)` to delegate to the pure functions: return
    `None` for empty/too-short/malformed payloads, otherwise construct and return a `HeartRate` with
    a timezone-aware `effective` (from an injectable `now` callable defaulting to `datetime.now(UTC)`)
    and the parser's `device_id`.
  - Keep byte decoding total (never raises); `HeartRate` assembly takes `device_id` + clock so the
    decode functions stay pure and clock/identity-free.
  - _Requirements: FR-3a.1, FR-3a.2, FR-3a.3, FR-3a.4, FR-3a.5_

  - [x] 1.1 Write parser payload fixtures and example tests
    - In `tests/adapters/conftest.py`, add the seven fixtures/constants from testing.md:
      `hr_payload_uint8_contact`, `hr_payload_uint8_no_contact`, `hr_payload_uint16_contact`,
      `hr_payload_uint16_no_contact`, `hr_payload_with_rr`, `hr_payload_truncated`, `hr_payload_empty`.
    - In `tests/adapters/test_parser.py`, assert each valid fixture parses to the expected `value`
      and `sensor_contact`, and that truncated/empty return `None`.
    - _Requirements: FR-3a.1, FR-3a.2, FR-3a.3, FR-3a.4_

  - [x] 1.2 Write property test: parser round-trips valid payloads
    - **Property 1: Parser round-trips valid payloads** — build valid payloads via Hypothesis
      strategies over uint8/uint16 value format, sensor-contact configuration, and optional
      energy-expended / RR-interval fields; assert `value` and `sensor_contact` match the encoding.
    - **Validates: Requirements FR-3a.1, FR-3a.2, FR-3a.3**

  - [x] 1.3 Write property test: parser never crashes on arbitrary bytes
    - **Property 2: Parser never crashes on arbitrary bytes** — `@given(st.binary())`, assert the
      result is `None` or a valid `HeartRate` and never raises.
    - **Validates: Requirements FR-3a.4**

- [x] 2. Implement the MockAdapter and the reusable DeviceAdapter contract suite
  - [x] 2.1 Implement `MockAdapter` (`adapters/builtin/mock.py`)
    - Implement `DeviceAdapter` fully without importing `bleak`: `supported_vitals = (HeartRate,)`,
      synthetic `device_info`, `state` transitions (`CONNECTING`→`CONNECTED` on `connect()`,
      `DISCONNECTED` on `disconnect()`), and a `vitals()` async generator.
    - Add an emission-mode parameter (`VALID`, `IMPLAUSIBLE`, `NO_SENSOR_CONTACT`) with optional
      interval/count so tests can drive each `ValidatorChain` branch; yield `HeartRate` with a
      timezone-aware `effective` and a small `asyncio.sleep` between yields.
    - _Requirements: FR-9_

  - [x] 2.2 Implement the reusable `DeviceAdapter` contract suite
    - Create `tests/adapters/contract.py` with a reusable parametrized suite asserting: concrete
      subclass of `DeviceAdapter` (no unimplemented abstracts), non-empty `supported_vitals` of
      `VitalSign` subclasses, `device_info` returns `DeviceInfo`, `state` returns `ConnectionState`,
      `vitals()` returns an async iterator, and (AST check) no module-level `bleak` import.
    - Wire it in `tests/adapters/test_mock.py` so `MockAdapter` runs and passes the suite.
    - _Requirements: FR-9, NFR-6_

  - [x] 2.3 Write ABC-contract instantiation tests
    - Assert each ABC (`VitalSign`, `ScalarVital`, `ComponentVital`, `DeviceAdapter`,
      `GattCharacteristicParser`, `BleHeartRateAdapter`, `Validator`, `VitalMapper`,
      `ObservationSink`, `ObservationStore`, `Authenticator`) raises `TypeError` on direct
      instantiation. Place ABC tests in the mirroring `tests/<package>/` files.
    - _Requirements: NFR-6_

  - [x] 2.4 Write the HeartRate metadata test
    - In `tests/vitals/test_heart_rate.py`, assert `HeartRate` has non-empty `loinc_code`,
      `us_core_profile` starting with `http://hl7.org/fhir/`, non-empty `ucum_unit`,
      `plausible_range` a `(float, float)` with `range[0] < range[1]`, and instantiates minimally.
    - _Requirements: FR-4.6, NFR-4_

- [x] 3. Checkpoint — Ensure all tests pass
  - Ensure `uv run ruff check .`, `uv run mypy src`, and `uv run pytest` all pass, ask the user if
    questions arise.

- [x] 4. Verify the validator chain against the design and add validator tests
  - Review `validation/base.py` and `validation/builtin/validators.py` (already implemented in the
    scaffold) against design §5 and FR-3b; adjust only if a test below reveals a gap
    (registration-order first-rejection, non-scalar pass-through, `VOF_HR_MIN/MAX` override,
    `sensor_contact is False` rejection with `None` accepted, `(device_id, effective, value)`
    duplicate set).
  - _Requirements: FR-3b.1, FR-3b.2, FR-3b.3, FR-3b.4, FR-3b.5_

  - [x] 4.1 Write property test: plausible-range validation
    - **Property 3: Plausible-range validation matches the in-range predicate** — accept iff
      `min <= value <= max` for generated values and configured/default bounds.
    - **Validates: Requirements FR-3b.3**

  - [x] 4.2 Write property test: sensor-contact validation
    - **Property 4: Sensor-contact validation rejects only explicit loss** — reject iff
      `sensor_contact is False` over `True`/`False`/`None`. Drive readings via `MockAdapter` modes
      where applicable.
    - **Validates: Requirements FR-3b.4**

  - [x] 4.3 Write property test: duplicate validation
    - **Property 5: Duplicate validation rejects repeated readings** — accept first occurrence of
      each `(device_id, effective, value)` triple, reject subsequent repeats.
    - **Validates: Requirements FR-3b.5**

  - [x] 4.4 Write property test: validator chain returns first rejection
    - **Property 6: Validator chain returns the first rejection** — over any ordered validator list
      and reading, `ValidatorChain.run` returns the first rejection or an accepted result.
    - **Validates: Requirements FR-3b.2**

- [x] 5. Implement FHIR builders, the scalar mapper, and the mapper registry
  - [x] 5.1 Implement resource builders (`fhir/builders.py`)
    - Implement `build_device`, `build_patient`, `build_capability_statement`,
      `build_operation_outcome` as plain functions returning `fhir.resources` models (imported inside
      their bodies). `build_device` uses a stable slugified id from `device_info.model`;
      `build_capability_statement` documents the read-only endpoints and `code`/`date`/`_sort`/
      `_count` params; `build_operation_outcome` carries one issue and never includes secrets or
      measurement values.
    - _Requirements: FR-11, FR-12, NFR-4_

  - [x] 5.2 Implement `ScalarVitalMapper` (`fhir/mappers.py`)
    - Implement `to_observation(vital, patient_ref, device_ref, issued)` building an `Observation`
      from `ScalarVital` class metadata: v4 UUID `id`, `meta.profile` from `us_core_profile`,
      `status="final"`, vital-signs `category`, LOINC `code`, `subject`/`device` references,
      `effectiveDateTime` (UTC) and `issued` both set, `valueQuantity` with UCUM `code` and
      `beats/minute` display. Construct via `fhir.resources` so validation runs; let `ValidationError`
      propagate to the orchestrator. Leave `ComponentVitalMapper` a roadmap stub.
    - _Requirements: FR-4.1, FR-4.2, FR-4.3, FR-4.4, FR-4.5, FR-4.6, FR-4.7, FR-4.8, NFR-4_

  - [x] 5.3 Register the mapper in `fhir/__init__.py`
    - Register `ScalarVitalMapper()` for `ScalarVital` (`register_mapper(ScalarVital, ...)`) as a
      package-load side effect so every scalar vital resolves via MRO through the existing
      `resolve_mapper`.
    - _Requirements: FR-4.9_

  - [x] 5.4 Write property test: mapper produces a valid US Core Observation
    - **Property 7: Mapper produces a valid US Core Observation** — assert construction succeeds and
      the fields per testing.md FHIR-validation checklist. FHIR validity asserted via
      `fhir.resources` construction, not re-implemented.
    - **Validates: Requirements FR-4.1, FR-4.2, FR-4.3, FR-4.4, FR-4.5, FR-4.6, FR-4.7, NFR-4**

  - [x] 5.5 Write property test: Observation ids are unique
    - **Property 8: Observation ids are unique** — across a sequence of mapped readings, all `id`
      values are distinct.
    - **Validates: Requirements FR-4.5**

  - [x] 5.6 Write property test: mapper resolves via the MRO
    - **Property 9: Mapper resolves via the MRO** — an unregistered `ScalarVital` subclass with valid
      metadata resolves to the `ScalarVital` mapper.
    - **Validates: Requirements FR-4.9**

- [x] 6. Implement the in-memory observation store
  - In `store/memory.py`, implement `InMemoryObservationStore(max_size)` as both `ObservationStore`
    and `ObservationSink` using an `OrderedDict` keyed by Observation `id` and an `asyncio.Lock`.
  - `publish` delegates to `add`; `add` evicts oldest via `popitem(last=False)` when at bound; `get`
    and `search` return deep copies (`model_copy(deep=True)`), never live references. `search`
    filters by LOINC `code` and `effectiveDateTime` range, sorts by `effectiveDateTime`
    (desc when `sort_desc`), and truncates to `count`. Starts empty every process.
  - _Requirements: FR-STORE.1, FR-STORE.2, FR-STORE.3, FR-STORE.4, FR-STORE.5, FR-STORE.6, FR-8_

  - [x] 6.1 Write property test: store bound and eviction
    - **Property 10: Store never exceeds its bound and evicts oldest** — final size ≤ `VOF_STORE_MAX`
      and retained items are the most-recently-added.
    - **Validates: Requirements FR-STORE.2**

  - [x] 6.2 Write property test: store reads return isolated snapshots
    - **Property 11: Store reads return isolated snapshots** — mutating a returned resource does not
      change store contents on a subsequent read.
    - **Validates: Requirements FR-STORE.4**

  - [x] 6.3 Write property test + empty-store example: search correctness
    - **Property 12: Search results honor filters, sort, and count** — entries match all supplied
      filters, `-date` sorts descending, entries ≤ `_count`, Bundle-equivalent `total` = match count,
      unsupported params ignored. Add an example test that a fresh store searches empty.
    - **Validates: Requirements FR-STORE.4, FR-11**

- [x] 7. Checkpoint — Ensure all tests pass
  - Ensure `uv run ruff check .`, `uv run mypy src`, and `uv run pytest` all pass, ask the user if
    questions arise.

- [x] 8. Implement the pipeline orchestrator
  - In `pipeline/orchestrator.py`, implement `Orchestrator(adapter, validator_chain, mapper, sinks)`
    `run()`: `await adapter.connect()`, then `async for vital in adapter.vitals()`: run the chain
    (on rejection log `INFO` with validator name + reason, **no value**, and continue); resolve the
    mapper via `resolve_mapper(type(vital))` and build the Observation with `issued=now(UTC)`
    (on `ValidationError` log `ERROR` and continue); fan out to each sink with per-sink
    `try/except` so one failing sink never stops the others.
  - Accept `patient_ref`/`device_ref` and an optional state-relay
    `Callable[[ConnectionState], Awaitable[None]]` injected by `cli.py` (no `dashboard` import).
  - _Requirements: FR-ORCH, FR-3b.6, FR-4.8, FR-6, FR-8, NFR-5_

  - [x] 8.1 Write property test: one failing sink does not stop the others
    - **Property 17: One failing sink does not stop the others** — with an arbitrary subset of sinks
      raising on `publish`, every non-failing sink still receives the Observation. Use `MockAdapter`
      as the source.
    - **Validates: Requirements FR-ORCH**

  - [x] 8.2 Write property test: measurement values never appear in logs at INFO+
    - **Property 15: Measurement values never appear in logs at INFO+** — use `caplog`; no `INFO`+
      record contains a reading's measurement value, including on rejection. Add an example that a
      rejected reading yields no `publish`.
    - **Validates: Requirements FR-3b.6, NFR-5**

- [x] 9. Implement the API auth, routes, and app factory
  - [x] 9.1 Implement `StaticTokenAuthenticator` (`api/auth.py`)
    - Implement `authenticate(credentials)` with `hmac.compare_digest(credentials, self._token)` —
      never `==`; the token never appears in logs or responses.
    - _Requirements: FR-12.3, FR-12.5, NFR-5_

  - [x] 9.2 Implement the route functions (`api/routes.py`)
    - Implement plain `async def` routes receiving `store` and `auth` via `Depends()`: a bearer-token
      auth dependency raising HTTP 401 + `OperationOutcome` (issue code `security`, never 403) on
      missing/invalid token; `get_metadata`; `search_observations` (parse `code`, `date` with
      `ge/le/gt/lt` prefixes, `_sort=-date`, `_count`; ignore unsupported params; wrap in a
      `searchset` `Bundle` with `total` = match count and per-entry `fullUrl` + `resource`);
      `get_observation`/`get_patient`/`get_device` returning the resource or 404 + `OperationOutcome`
      (issue code `not-found`); `application/fhir+json` on every response; no write endpoints.
    - _Requirements: FR-11, FR-12.1, FR-12.3, FR-12.4, FR-12.5, FR-8_

  - [x] 9.3 Implement `create_app` (`api/app.py`)
    - Build the `FastAPI` app: register routes, provide `Depends()` providers for the
      `ObservationStore` and `Authenticator` (instances injected from `cli.py`, no module-level
      singletons), mount the dashboard static files, register the WebSocket endpoint (token via
      query parameter validated with the shared `Authenticator` before `accept()`), and set
      `application/fhir+json` on FHIR responses.
    - _Requirements: FR-11, FR-12.2, NFR-5_

  - [x] 9.4 Write property + example tests: auth rejects non-matching tokens
    - **Property 13: Auth rejects every non-matching token** — via `httpx.AsyncClient` against the
      ASGI app (no live server): any non-matching/missing token → 401 `OperationOutcome` (issue code
      `security`, never 403); correct token → success. Include no-header, wrong-token, correct-token,
      and 404-unknown-id examples plus the `application/fhir+json` content-type assertion.
    - **Validates: Requirements FR-12.1, FR-12.2, FR-12.3, FR-12.4**

  - [x] 9.5 Write property test: the token never leaks
    - **Property 14: The token never leaks** — for valid and invalid requests, `VOF_API_TOKEN` never
      appears in the response body, any header, or any captured log record at any level.
    - **Validates: Requirements FR-12.5, NFR-5**

- [x] 10. Checkpoint — Ensure all tests pass
  - Ensure `uv run ruff check .`, `uv run mypy src`, and `uv run pytest` all pass, ask the user if
    questions arise.

- [x] 11. Implement the dashboard broadcaster and static assets
  - [x] 11.1 Implement `DashboardBroadcaster` (`dashboard/broadcaster.py`)
    - Implement the `ObservationSink`: maintain an authenticated-WebSocket set guarded by an
      `asyncio.Lock`; `register`/`unregister` (called by the endpoint after the token check);
      `publish(obs)` serializes once with `obs.model_dump_json()`, wraps it in the `observation`
      envelope, and sends to every connection, catching per-connection errors and unregistering
      closed sockets; `on_state_change(state)` sends a `connection_state` envelope to all clients.
    - _Requirements: FR-10, FR-6, FR-12.2, FR-8_

  - [x] 11.2 Implement the static dashboard (`dashboard/static/`)
    - In `index.html`, `style.css`, `app.js` (no build step): token entry field; display latest
      heart-rate value, Observation timestamp, and connection status in plain language for
      non-technical users; show the BLE unauthenticated-channel disclaimer from
      `security-privacy.md`; `app.js` opens the WebSocket, updates the DOM from pushed observation and
      state envelopes, stops showing new values while disconnected, and resumes on reconnect — no
      polling, no page reload.
    - _Requirements: FR-5, FR-6, FR-7, FR-10, NFR-3_

  - [x] 11.3 Write property + example tests: broadcaster fan-out
    - **Property 16: Broadcaster fans out FHIR JSON to every client** — with in-memory fake
      WebSocket clients, every registered client receives an `observation` envelope whose `resource`
      round-trips via `model_validate_json` to the published Observation. Add example tests for the
      `connection_state` envelope and a static-asset check confirming the BLE disclaimer text.
    - **Validates: Requirements FR-10, FR-6**

- [x] 12. Wire the composition root (`cli.py`)
  - Implement `main()` as the only place that names concrete classes and the only caller of
    `asyncio.run()`: load `Settings()` once (never log config); `argparse --adapter`; resolve
    `mock`→`MockAdapter`, `miband10`→`MiBand10Adapter`, else import a fully qualified
    `package.module.ClassName` via `importlib`; build `Patient` from `VOF_PATIENT_ID` and `Device`
    from `adapter.device_info` and derive `Patient/<id>`/`Device/<id>` refs; build the
    `ValidatorChain` from `hr_min`/`hr_max`; construct `InMemoryObservationStore(store_max)` and
    `DashboardBroadcaster()`; wire the `Orchestrator` with `sinks=[store, broadcaster]` and the
    state-relay pointing at `broadcaster.on_state_change`; `create_app()` injecting the store +
    `StaticTokenAuthenticator(api_token)` + broadcaster; run uvicorn (bind `VOF_HOST` default
    `127.0.0.1` / `VOF_PORT` default `8000`) and `orchestrator.run()` concurrently in one
    `asyncio.run`.
  - _Requirements: FR-ORCH, FR-3b.1, FR-11, FR-12.1, NFR-5_

- [x] 13. Cite the Bluetooth Heart Rate Measurement specification in `docs/`
  - Add a `docs/` entry citing the Bluetooth SIG Heart Rate Service / Heart Rate Measurement
    (0x2A37) specification used to implement the parser: specification name, version, and URL or
    publication date, as required by FR-3a and `security-privacy.md` protocol-sourcing rules.
  - _Requirements: FR-3a.6_

- [x] 14. Implement the BLE adapters (hardware-marked)
  - [x] 14.1 Implement `BleHeartRateAdapter` connection lifecycle (`adapters/ble.py`)
    - Implement the concrete lifecycle on the ABC (subclasses still implement only `matches()` and
      `device_info`): lazy `bleak` import guarded to raise a clear `RuntimeError` on
      missing/unavailable stack; `connect()` scans/filters via `matches()` + optional
      `VOF_DEVICE_NAME`, connects to one device, subscribes to `0x2A37`, sets `CONNECTED`; the
      notification callback only does `loop.call_soon_threadsafe(self._queue.put_nowait, bytes(data))`;
      `vitals()` dequeues, parses via `HeartRateMeasurementParser`, drops `None` at `DEBUG`, yields
      indefinitely; a reconnection loop sets `RECONNECTING` and retries with capped backoff;
      `disconnect()` stops notifications, disconnects, sets `DISCONNECTED`, unblocks `vitals()`.
      A private `_set_state()` invokes the injected state callback.
    - _Requirements: FR-1, FR-2, FR-6, NFR-2_

  - [x] 14.2 Implement `MiBand10Adapter` (`adapters/builtin/miband10.py`)
    - Implement `matches(advertisement)` by the Xiaomi Smart Band 10 advertised name / HRS service
      UUID and `device_info` returning `DeviceInfo(manufacturer="Xiaomi", model="Smart Band 10",
      identifiers={"bluetooth_address": <addr>})`; `supported_vitals = (HeartRate,)`. No scanning or
      parsing logic (handled by the base).
    - _Requirements: FR-1_

  - [x] 14.3 Write hardware-marked BLE adapter tests
    - Add `@pytest.mark.hardware` tests (e.g. `tests/adapters/test_miband10_hardware.py`); `bleak`
      may be imported only inside these hardware-marked modules. These are deselected in CI.
    - _Requirements: FR-1, FR-2, NFR-2, NFR-6_

- [x] 15. Final verification
  - Run `uv run ruff check .`, `uv run mypy src`, and `uv run pytest` (fast suite) and confirm all
    pass. Confirm `tests/test_dependency_directions.py` (Property 18) still passes. Confirm no
    `raise NotImplementedError` or bare `...` stubs remain in the implemented packages (`vitals`,
    `adapters`, `validation`, `fhir`, `pipeline`, `store`, `api`, `dashboard`, `cli`). Fix any
    lint/type/test failures found.
  - _Requirements: NFR-4, NFR-5, NFR-6_

- [x] 16. Prepend the CHANGELOG entry for the heart-rate pipeline MVP
  - Prepend a `CHANGELOG.md` entry (per `changelog-rules.md`) dated `[2026-09]`, titled with the
    `(spec/hr-pipeline)` suffix, summarizing the MVP and listing the implemented modules (parser,
    `MockAdapter`, BLE adapters, validators usage, FHIR builders/mapper/registry,
    `InMemoryObservationStore`, orchestrator, API auth/routes/app, `DashboardBroadcaster` + static
    dashboard, `cli.py` wiring) and referencing FR-1..FR-12 / NFR-1..NFR-6.
  - _Requirements: NFR-6_

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core
  implementation tasks are never marked optional.
- The CHANGELOG task (16) is the spec's final task and is not optional.
- Each task references specific FR-*/NFR-* sub-requirement IDs for traceability; property test
  sub-tasks additionally name the design property number(s) they implement.
- Checkpoints (tasks 3, 7, 10) ensure the project stays green (lint + mypy + fast pytest) at
  natural breaks.
- BLE work (task 14) is intentionally last: it is hardware-marked and not needed for the fast suite,
  so the MVP pipeline (mock path → FHIR → store → API → dashboard) is fully testable before it.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "13"] },
    { "id": 1, "tasks": ["1.1", "1.2", "1.3", "2.1", "5.1"] },
    { "id": 2, "tasks": ["2.2", "5.2", "6"] },
    { "id": 3, "tasks": ["2.3", "2.4", "4", "5.3", "6.1", "6.2", "6.3", "14.1"] },
    { "id": 4, "tasks": ["4.1", "4.2", "4.3", "4.4", "5.4", "5.5", "5.6", "8", "14.2"] },
    { "id": 5, "tasks": ["8.1", "8.2", "9.1", "9.2", "11.1", "14.3"] },
    { "id": 6, "tasks": ["9.3", "11.2"] },
    { "id": 7, "tasks": ["9.4", "9.5", "11.3", "12"] },
    { "id": 8, "tasks": ["15"] },
    { "id": 9, "tasks": ["16"] }
  ]
}
```
