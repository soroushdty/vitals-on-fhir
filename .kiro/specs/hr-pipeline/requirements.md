# Requirements Document

**Spec: hr-pipeline**

## Introduction

This spec implements the complete heart-rate MVP pipeline for vitals-on-fhir: the full
acquisition-to-dashboard path that turns a live Bluetooth heart-rate stream (or simulated
readings) into HL7 FHIR R4 Observations served over a read-only, token-authenticated REST API
and pushed to a live web dashboard.

The `repo-scaffold` spec created every package under `src/vitals_on_fhir/` as stubs with correct
ABC signatures, `__all__` exports, config, a CLI stub, a test skeleton, and a passing
`test_dependency_directions.py`. This spec fills in the business logic behind those stubs. When it
is complete, no stubs remain and the MVP works end to end.

Each requirement below is traced to the product steering document's functional (FR-*) and
non-functional (NFR-*) requirement IDs. These IDs are preserved deliberately for the planned
preprint; do not renumber them. Acceptance criteria follow EARS patterns and INCOSE quality
rules. The document mirrors the FR-/NFR-heading, bullet-acceptance-criteria style of
`repo-scaffold/requirements.md`.

## Glossary

- **Pipeline**: the end-to-end vitals-on-fhir system composed of the components below.
- **Adapter**: a `DeviceAdapter` implementation that yields `VitalSign` domain objects.
- **BLE_Adapter**: a `BleHeartRateAdapter` subclass acquiring heart rate over Bluetooth Low Energy.
- **Mock_Adapter**: the `MockAdapter` concrete adapter producing simulated readings without hardware.
- **Parser**: the `HeartRateMeasurementParser` that decodes GATT `0x2A37` payloads into `HeartRate` objects.
- **Validator_Chain**: the `ValidatorChain` running the configured validators in registration order.
- **Mapper**: the `ScalarVitalMapper` converting a `VitalSign` to a FHIR `Observation`.
- **Store**: the `InMemoryObservationStore`, which is both an `ObservationStore` and an `ObservationSink`.
- **Broadcaster**: the `DashboardBroadcaster`, an `ObservationSink` that pushes to WebSocket clients.
- **Orchestrator**: the pipeline component wiring Adapter → Validator_Chain → Mapper → sinks.
- **Authenticator**: the `StaticTokenAuthenticator` validating the bearer token.
- **API**: the read-only FHIR REST interface exposed by the FastAPI app.
- **Dashboard**: the browser UI served from `dashboard/static/`.
- **CLI**: `cli.py`, the composition root — the only module that instantiates concrete classes.
- **Connection_State**: the `ConnectionState` enum (`DISCONNECTED`, `CONNECTING`, `CONNECTED`, `RECONNECTING`).
- **Reading**: a single decoded, well-formed `HeartRate` measurement.
- **Observation**: a `fhir.resources` R4 `Observation` model instance.
- **HRS**: the Bluetooth Heart Rate Service, GATT service UUID `0x180D`.
- **HR_Measurement_Characteristic**: GATT characteristic UUID `0x2A37`.

---

## Requirements

### Functional requirements

#### FR-1 — BLE device connection and connection-state monitoring
*Traces to product FR-1.*

- WHEN the CLI selects a BLE_Adapter, THE BLE_Adapter SHALL scan for a device advertising the HRS,
  optionally filtered by the `VOF_DEVICE_NAME` name filter when configured.
- WHEN a matching device is discovered, THE BLE_Adapter SHALL connect to it and maintain a single
  connection for the monitoring session.
- THE BLE_Adapter SHALL expose the current Connection_State through its `state` property for the
  whole session.
- WHEN the Connection_State changes, THE BLE_Adapter SHALL update the value returned by its `state`
  property to the new Connection_State.
- THE Pipeline SHALL support exactly one connected device at a time.
- THE BLE_Adapter SHALL import `bleak` lazily inside the methods that use it, never at module level.

#### FR-2 — Real-time heart-rate acquisition
*Traces to product FR-2.*

- WHILE the BLE_Adapter Connection_State is `CONNECTED`, THE BLE_Adapter SHALL subscribe to
  notifications from the HR_Measurement_Characteristic.
- WHEN a notification is received on the HR_Measurement_Characteristic, THE BLE_Adapter SHALL pass
  the payload to the Parser and yield the resulting Reading from its `vitals()` async generator
  without requiring user intervention.
- WHEN a BLE notification arrives on a thread other than the event loop, THE BLE_Adapter SHALL
  hand the payload to the event loop safely (for example via `loop.call_soon_threadsafe`) rather
  than performing async work directly in the callback thread.
- THE BLE_Adapter `vitals()` generator SHALL yield Readings indefinitely until the adapter is
  disconnected.

#### FR-9 — Mock adapter
*Traces to product FR-9.*

- THE Mock_Adapter SHALL implement `DeviceAdapter` and produce simulated `HeartRate` Readings
  without importing `bleak`.
- THE Mock_Adapter SHALL be configurable to emit valid Readings, implausible-value Readings, and
  Readings with `sensor_contact` set to `False`, so the full Validator_Chain can be exercised in tests.
- WHEN the Mock_Adapter is connected, THE Mock_Adapter SHALL report Connection_State transitions
  consistent with the `DeviceAdapter` contract (`CONNECTING` then `CONNECTED`).
- THE Mock_Adapter SHALL yield each simulated Reading with a timezone-aware `effective` timestamp.

#### FR-3a — Heart Rate Measurement payload parsing
*Traces to product FR-3 (parsing half).*

- WHEN the Parser receives a payload, THE Parser SHALL read the flags byte to determine whether the
  heart-rate value is uint8 or uint16 format and decode the value accordingly.
- WHEN the flags byte indicates sensor contact is supported, THE Parser SHALL set the Reading's
  `sensor_contact` to the reported boolean; WHERE sensor contact is not supported by the flags byte,
  THE Parser SHALL set `sensor_contact` to `None`.
- WHEN the flags byte indicates energy-expended or RR-interval fields are present, THE Parser SHALL
  account for those fields when computing field offsets so the heart-rate value is decoded from the
  correct position.
- IF a payload is too short for the fields its flags byte declares, or is otherwise malformed, THEN
  THE Parser SHALL return `None` and THE BLE_Adapter SHALL drop the payload without yielding a Reading.
- THE Parser byte-level decoding SHALL be implemented as pure functions that the Parser class delegates to.
- THE `docs/` directory SHALL cite the Bluetooth SIG Heart Rate Service / Heart Rate Measurement
  specification (name, version, and URL or publication date) used to implement the Parser.

#### FR-3b — Validation chain
*Traces to product FR-3 (validation half).*

- WHEN a well-formed Reading is produced, THE Orchestrator SHALL pass it through the Validator_Chain
  before mapping.
- WHEN the Validator_Chain runs, THE Validator_Chain SHALL execute validators in registration order
  and return the first rejection, or an accepted result when all validators pass.
- IF a Reading's value is outside the plausible range, THEN THE PlausibleRangeValidator SHALL reject it;
  THE PlausibleRangeValidator SHALL use the range from `VOF_HR_MIN` and `VOF_HR_MAX` when configured,
  defaulting to the `HeartRate` class `plausible_range` of 20–250 bpm otherwise.
- IF a Reading's `sensor_contact` is `False`, THEN THE SensorContactValidator SHALL reject it;
  WHERE `sensor_contact` is `None`, THE SensorContactValidator SHALL accept the Reading.
- IF a Reading with the same `(device_id, effective, value)` has already been seen in the session,
  THEN THE DuplicateValidator SHALL reject it.
- WHEN the Validator_Chain rejects a Reading, THE Pipeline SHALL log the rejection at `INFO` level
  without including the measurement value, and SHALL NOT produce an Observation for that Reading.

#### FR-4 — FHIR Observation generation
*Traces to product FR-4.*

- WHEN a Reading is accepted by the Validator_Chain, THE Mapper SHALL convert it to a FHIR R4
  `Observation` conforming to the US Core Heart Rate profile.
- THE Mapper SHALL set `status` to `final`, the vital-signs `category` coding, `code` to LOINC
  `8867-4`, and `valueQuantity` with UCUM unit `/min` and the numeric value.
- THE Mapper SHALL set `subject` to the configured Patient reference and `device` to the Device
  reference for the originating adapter.
- THE Mapper SHALL set `effectiveDateTime` from the Reading's `effective` time (converted to UTC
  ISO 8601) and `issued` to the processing time, setting both fields.
- THE Mapper SHALL assign each Observation a v4 UUID as its `id`.
- THE Mapper SHALL set `meta.profile` to the `HeartRate` class `us_core_profile` value.
- THE Mapper SHALL construct the Observation using `fhir.resources` model classes so that model
  validation runs at construction time.
- IF Observation construction fails validation, THEN THE Pipeline SHALL log the failure at `ERROR`
  level and SHALL NOT serve or store an invalid Observation.
- THE Mapper SHALL resolve the mapper for a vital-sign class by walking its MRO, so a new
  `ScalarVital` subclass with correct metadata needs no new mapper code.

#### FR-8 — Standardized representation only
*Traces to product FR-8.*

- THE Pipeline SHALL represent every processed measurement as a FHIR Observation.
- THE Pipeline SHALL NOT expose measurement data through any non-FHIR side channel; the Store, API,
  and Broadcaster SHALL carry measurement data only as FHIR Observations.

#### FR-STORE — In-memory observation store
*Traces to product FR-11 storage needs, NFR-5 retention, and the object-model store contract.*

- WHEN the Orchestrator publishes an Observation, THE Store SHALL add it to the in-memory collection.
- WHILE the number of stored Observations equals `VOF_STORE_MAX`, WHEN a new Observation is added,
  THE Store SHALL evict the oldest Observation before retaining the new one.
- THE Store SHALL guard all reads and writes with an `asyncio.Lock`.
- WHEN the Store returns results from `get` or `search`, THE Store SHALL return snapshots (copies),
  never live references to internal state.
- THE Store SHALL implement both the `ObservationStore` and `ObservationSink` contracts.
- WHEN the process restarts, THE Store SHALL start empty, retaining no Observations from prior sessions.

#### FR-11 — Read-only FHIR REST API
*Traces to product FR-11.*

- WHEN `GET /fhir/metadata` is requested, THE API SHALL return a `CapabilityStatement` documenting
  the supported endpoints and search parameters.
- WHEN `GET /fhir/Observation` is requested, THE API SHALL return a `Bundle` of type `searchset`
  whose `total` reflects the number of matching Observations and whose entries each carry a
  `fullUrl` and the full Observation `resource`.
- WHERE the `code` search parameter is supplied, THE API SHALL filter Observations by `system|code`.
- WHERE the `date` search parameter is supplied with a `ge`, `le`, `gt`, or `lt` prefix, THE API
  SHALL filter Observations by `effectiveDateTime` accordingly.
- WHERE `_sort=-date` is supplied, THE API SHALL sort results by descending `effectiveDateTime`.
- WHERE `_count` is supplied, THE API SHALL limit the number of returned entries to that count.
- WHERE an unsupported search parameter is supplied, THE API SHALL ignore it without returning an error.
- WHEN `GET /fhir/Observation/{id}`, `GET /fhir/Patient/{id}`, or `GET /fhir/Device/{id}` is
  requested for an existing resource, THE API SHALL return that resource.
- IF a requested resource does not exist, THEN THE API SHALL respond with HTTP 404 and an
  `OperationOutcome` carrying issue code `not-found`.
- THE API SHALL set `Content-Type: application/fhir+json` on every response, including error
  OperationOutcomes.
- THE API SHALL NOT expose any write operation (create, update, or delete) in the MVP.
- THE API route functions SHALL be plain `async def` functions receiving the Store and Authenticator
  via FastAPI `Depends()`.

#### FR-12 — Token authentication
*Traces to product FR-12 and the security steering doc.*

- WHEN any API request is received, THE API SHALL require a valid bearer token matching `VOF_API_TOKEN`.
- WHEN a dashboard WebSocket connection is opened, THE Broadcaster SHALL require a valid bearer token
  matching `VOF_API_TOKEN` before accepting the connection.
- THE Authenticator SHALL compare the supplied token to `VOF_API_TOKEN` using a constant-time
  comparison (for example `hmac.compare_digest`), never using `==`.
- IF a request or WebSocket connection presents a missing or invalid token, THEN THE API SHALL
  respond with HTTP 401 and an `OperationOutcome` carrying issue code `security`, and SHALL NOT
  respond with HTTP 403.
- THE API SHALL NOT include the token value in any response body, header, or log message.

#### FR-5 — Live dashboard content
*Traces to product FR-5.*

- WHILE connected and receiving Readings, THE Dashboard SHALL display the latest heart-rate value,
  the Observation timestamp, and the current connection status.
- THE Dashboard SHALL present its content in terms understandable to a non-technical user.
- THE Dashboard SHALL display the BLE unauthenticated-channel disclaimer described in the security
  steering document.

#### FR-6 — Connection-status behavior on disconnect and reconnect
*Traces to product FR-6.*

- WHEN the adapter disconnects, THE Broadcaster SHALL relay the disconnection to the Dashboard and
  THE Dashboard SHALL show the disconnected status.
- WHILE the adapter is disconnected, THE Dashboard SHALL stop presenting new heart-rate values.
- WHEN the adapter reconnects, THE Pipeline SHALL resume acquisition automatically and THE Dashboard
  SHALL resume presenting new values without user action.

#### FR-7 — Continuous monitoring
*Traces to product FR-7.*

- THE Dashboard SHALL update continuously during a session without requiring a manual page refresh
  or a process restart.

#### FR-10 — WebSocket server push
*Traces to product FR-10.*

- WHEN the Orchestrator publishes an Observation, THE Broadcaster SHALL serialize it to FHIR JSON
  and send it to every connected, authenticated WebSocket client.
- WHEN a Connection_State change occurs, THE Broadcaster SHALL send that state change to every
  connected, authenticated WebSocket client.
- THE Dashboard SHALL update from server-pushed WebSocket messages without polling or page reload.

#### FR-ORCH — Orchestration and composition root
*Traces to product FR-1..FR-10 wiring and the object-model pipeline/CLI contracts.*

- THE Orchestrator SHALL wire the flow Adapter → Validator_Chain → Mapper → registered sinks,
  depending only on ABCs.
- WHEN a sink raises during `publish`, THE Orchestrator SHALL log the error and continue delivering
  to the remaining sinks so one failing sink does not stop the others.
- THE CLI SHALL be the only module that instantiates concrete classes and SHALL be the only module
  that calls `asyncio.run()`.
- WHEN the CLI starts, THE CLI SHALL load `Settings` once via pydantic-settings and pass
  configuration explicitly to each component that needs it.
- WHEN the `--adapter` value is `mock` or `miband10`, THE CLI SHALL instantiate the corresponding
  built-in adapter; WHERE the value is a fully qualified class path, THE CLI SHALL import and
  instantiate that class without requiring repository changes.
- WHEN the CLI starts, THE CLI SHALL build the Patient resource from `VOF_PATIENT_ID` and the Device
  resource from the adapter's `DeviceInfo`, and pass their reference strings to the Mapper.
- WHEN the CLI starts, THE CLI SHALL bind the server to `VOF_HOST` (default `127.0.0.1`) and
  `VOF_PORT` (default `8000`).

---

### Non-functional requirements

#### NFR-1 — Near-real-time performance
*Traces to product NFR-1.*

- WHEN a Reading is accepted, THE Pipeline SHALL deliver the resulting Observation to the Dashboard
  promptly after the originating notification, without introducing buffering delays beyond those
  required by the async pipeline.

#### NFR-2 — Reliability and automatic recovery
*Traces to product NFR-2.*

- WHEN the device connection is lost, THE BLE_Adapter SHALL detect the disconnection and transition
  Connection_State to `RECONNECTING`.
- WHILE in `RECONNECTING`, THE BLE_Adapter SHALL attempt to re-establish the connection and, on
  success, resume acquisition and transition to `CONNECTED` without user action.

#### NFR-3 — Usability
*Traces to product NFR-3.*

- THE Dashboard SHALL present heart rate, timestamp, and connection status using plain language and
  layout suitable for a non-technical user.

#### NFR-4 — Interoperability
*Traces to product NFR-4.*

- THE Pipeline SHALL produce Observations conforming to FHIR R4 (4.0.1) and the US Core Heart Rate
  profile, using LOINC and UCUM codings.
- THE Pipeline SHALL validate every generated resource with `fhir.resources` model validation before
  serving or storing it.

#### NFR-5 — Security and privacy
*Traces to product NFR-5 and the security steering doc.*

- THE Pipeline SHALL require the bearer token on every API request and every dashboard WebSocket
  connection.
- THE CLI SHALL bind to `127.0.0.1` by default, requiring explicit `VOF_HOST` override for any other
  bind address.
- THE Pipeline SHALL NOT include `VOF_API_TOKEN` in any log message, exception message, or error
  response at any level.
- THE Pipeline SHALL NOT include measurement values in log messages at `INFO` level or above;
  measurement values MAY appear only at `DEBUG`.
- Every source file added by this spec SHALL begin with `# SPDX-License-Identifier: AGPL-3.0-or-later`.

#### NFR-6 — Maintainability
*Traces to product NFR-6.*

- After this spec is implemented, `uv run pytest tests/test_dependency_directions.py` SHALL pass,
  confirming no forbidden cross-package imports were introduced.
- THE test suite SHALL include ABC-contract and behavior tests for the adapters, parser, validators,
  mapper, store, API, and broadcaster, and the fast suite SHALL pass without hardware.
- THE spec's final task SHALL add a `CHANGELOG.md` entry recording the heart-rate pipeline MVP.

---

## Out of scope

This spec explicitly excludes, per the product steering document's permanent out-of-scope list:

- Vital signs other than heart rate (the class hierarchy stays ready for them; no logic is added).
- Multiple simultaneous connected devices.
- Persistence beyond in-memory storage (no database, no disk, no remote store).
- Remote or cloud deployment and exposure to untrusted networks.
- SMART on FHIR authentication (roadmap; not stubbed or referenced in MVP code).
- Writing to external EHRs or FHIR servers, and any write operation on the local API.
- Historical on-device data retrieval.
- Proprietary or reverse-engineered device protocols and any circumvention of device security.
