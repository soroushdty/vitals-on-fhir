# Changelog

All significant changes to vitals-on-fhir are recorded here.
This file is permanent and is never truncated or rewritten. See `changelog-rules.md` for the entry format and policy.

---

## [2026-09] — Heart rate pipeline MVP (spec/hr-pipeline)

Fills in the business logic behind the scaffold stubs so the heart-rate MVP runs end to end:
BLE and mock acquisition, payload parsing, validation, FHIR mapping, in-memory storage, a
read-only FHIR REST API with token auth, and a live WebSocket dashboard. Implements FR-1..FR-12
and NFR-1..NFR-6.

- Added: `adapters/parser.py` — `HeartRateMeasurementParser` plus pure decoding functions
  (`parse_flags`, `hr_value_size`, `required_length`, `decode_hr_value`, `decode_sensor_contact`)
  for the Bluetooth Heart Rate Measurement characteristic `0x2A37` (FR-3a)
- Added: `adapters/builtin/mock.py` — `MockAdapter` with `VALID`/`IMPLAUSIBLE`/`NO_SENSOR_CONTACT`
  emission modes, no `bleak` dependency (FR-9)
- Added: `adapters/ble.py` — `BleHeartRateAdapter` connection/subscribe/reconnect lifecycle with
  lazy `bleak` import; `adapters/builtin/miband10.py` — `MiBand10Adapter` (FR-1, FR-2, FR-6, NFR-2)
- Added: `validation/builtin/validators.py` usage via `ValidatorChain` —
  `PlausibleRangeValidator`, `SensorContactValidator`, `DuplicateValidator` (FR-3b)
- Added: `fhir/builders.py` (`build_device`, `build_patient`, `build_capability_statement`,
  `build_operation_outcome`), `fhir/mappers.py` — `ScalarVitalMapper`, and `ScalarVital` mapper
  registration in `fhir/__init__.py` resolved via MRO (FR-4, NFR-4)
- Added: `store/memory.py` — `InMemoryObservationStore`, a bounded `ObservationStore` and
  `ObservationSink` returning deep-copied snapshots (FR-STORE, FR-8)
- Added: `pipeline/orchestrator.py` — `Orchestrator` wiring adapter → `ValidatorChain` → mapper →
  sinks with per-sink isolation and value-free `INFO` rejection logging (FR-ORCH, NFR-5)
- Added: `api/auth.py` — `StaticTokenAuthenticator` (constant-time `hmac.compare_digest`);
  `api/routes.py` — read-only FHIR endpoints (`GET /fhir/metadata`, `GET /fhir/Observation`,
  `GET /fhir/Observation/{id}`, `GET /fhir/Patient/{id}`, `GET /fhir/Device/{id}`) returning
  `application/fhir+json`; `api/app.py` — `create_app` factory with dashboard WebSocket
  (FR-11, FR-12, NFR-5)
- Added: `dashboard/broadcaster.py` — `DashboardBroadcaster` (`ObservationSink` + WebSocket push)
  and `dashboard/static/` (`index.html`, `style.css`, `app.js`, no build step) (FR-5, FR-6, FR-7,
  FR-10, NFR-3)
- Added: `cli.py` — composition root wiring adapter selection, `ValidatorChain`, store, broadcaster,
  orchestrator, and app under a single `asyncio.run`; binds `VOF_HOST`/`VOF_PORT` (FR-ORCH, NFR-5)
- Uses config variables `VOF_HR_MIN`, `VOF_HR_MAX`, `VOF_PATIENT_ID`, `VOF_STORE_MAX`, `VOF_ADAPTER`,
  `VOF_DEVICE_NAME`, `VOF_API_TOKEN`, `VOF_HOST`, `VOF_PORT`
- Added: `docs/protocol-heart-rate-measurement.md` citing the Bluetooth SIG Heart Rate Service /
  Heart Rate Measurement (`0x2A37`) specification used for the parser (FR-3a)

## [2026-09] — Repository scaffold (spec/repo-scaffold)

Creates the complete skeleton of the vitals-on-fhir repository: all packages,
module stubs, configuration, tooling, and top-level files. No business logic
is implemented; all modules contain only correct signatures and `...` bodies.

- Added: full `src/vitals_on_fhir/` package tree (stubs only)
- Added: `tests/` skeleton with `test_dependency_directions.py` (AST-based enforcement)
- Added: `pyproject.toml` with ruff, mypy strict, pytest, and uv configuration
- Added: `config.py` — `Settings` with all `VOF_*` variables
- Added: `cli.py` — composition root stub
- Added: `.env.example` listing all configuration variables
- Added: `.github/workflows/ci.yml` — four-step CI pipeline
- Ported `test_dependency_directions.py` pattern from EviTrace (GPL-3.0); recorded in NOTICE.

## [2026-09] — Steering layer

Added eight steering documents under `.kiro/steering/` establishing the authoritative rules
for all future spec-driven work: product scope, technical stack, project structure, object model,
FHIR conventions, security and provenance, testing strategy, and changelog policy.

- Added: `.kiro/steering/product.md` — mission, FR/NFR IDs, use cases, MVP scope, roadmap
- Added: `.kiro/steering/tech.md` — stack, commands, config variables, async and coding conventions, CI
- Added: `.kiro/steering/structure.md` — directory layout, module responsibilities, dependency-direction rules, naming conventions
- Added: `.kiro/steering/object-model.md` — full ABC hierarchy, OOP conventions, extension recipes
- Added: `.kiro/steering/fhir-conventions.md` — FHIR version, canonical Observation shape, mapping rules, Bundle/search, OperationOutcome
- Added: `.kiro/steering/security-privacy.md` — auth rules, secret handling, logging restrictions, BLE disclaimer, HIPAA statement, legal and provenance rules
- Added: `.kiro/steering/testing.md` — test strategy, contract tests, Hypothesis property tests, payload fixtures, hardware marker
- Added: `.kiro/steering/changelog-rules.md` — entry format, when to add/skip, agent responsibility
