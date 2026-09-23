# Implementation Plan

**Spec: home-health-devices** (blood pressure — first phase-2 slice)

Each task is small, verifiable, and traces to requirements. Order minimizes regression risk: the
domain model and the behavior-preserving BLE extraction come first (guarded by the existing 74-test
suite), then parsing, mapping, validation, config, wiring, and docs. After every task run
`uv run ruff check .`, `uv run mypy src`, and `uv run pytest`; the existing suite plus
`tests/test_dependency_directions.py` must stay green throughout (NFR-HH-1, NFR-HH-2, NFR-HH-6).
Every new source file starts with `# SPDX-License-Identifier: AGPL-3.0-or-later` (NFR-HH-4).

- [x] 1. Define the `ComponentVital` concrete shape and `ComponentSpec`
  - Add frozen `ComponentSpec(field_name, loinc_code, ucum_unit, default_range)` to `vitals/base.py`.
  - Give `ComponentVital` a `components: ClassVar[tuple[ComponentSpec, ...]]` and a
    `component_values() -> tuple[tuple[ComponentSpec, float], ...]` method reading named fields in order.
  - Extend metadata enforcement so a concrete `ComponentVital` failing to declare `components`
    (non-empty) or whose `spec.field_name` is not an actual field raises at import time.
  - Export `ComponentSpec` from `vitals/__init__.py` under `# ABCs`/value objects as appropriate.
  - Unit tests: `component_values()` order; import-time raise on missing `components` / bad field name.
  - _Requirements: FR-HH-1, NFR-HH-1, NFR-HH-2_

- [x] 2. Add the `BloodPressure` vital-sign type
  - Create `vitals/builtin/blood_pressure.py`: frozen `BloodPressure(ComponentVital)` with panel
    `loinc_code="85354-9"`, US Core BP `us_core_profile`, `components` (systolic 8480-6, diastolic
    8462-4, `mm[Hg]`, sane `default_range`s), and `systolic`/`diastolic` float fields. No MAP.
  - Export from `vitals/__init__.py` under `# Concrete defaults`.
  - Unit tests: `__init_subclass__` accepts the complete class; a deliberately incomplete local
    subclass raises; instances are frozen; `component_values()` yields systolic then diastolic.
  - _Requirements: FR-HH-2, FR-HH-1_

- [x] 3. Extract the BLE lifecycle into a composed `BleConnection` (behavior-preserving)
  - In `adapters/ble.py`, introduce `BleConnection` holding the scan/connect/subscribe, threadsafe
    queue, capped-backoff reconnect, disconnect, and state-callback logic, parameterized by
    `service_uuid`, `characteristic_uuid`, `matches`, `parser_factory`, `device_name`, `on_state_change`.
  - Refactor `BleHeartRateAdapter` to construct and delegate to a `BleConnection` (HR UUIDs +
    `HeartRateMeasurementParser` factory) while keeping its exact public surface: exported name,
    abstract `matches`/`device_info`, constructor signature, and `state`/`connect`/`disconnect`/`vitals`.
  - Keep `bleak` imported lazily inside `BleConnection` methods only; no module-level import.
  - Verify: the full existing suite and `test_dependency_directions.py` pass unchanged (the guardrail).
    `MiBand10Adapter` untouched.
  - _Requirements: FR-HH-4, NFR-HH-1, NFR-HH-2, NFR-HH-6_

- [x] 4. Implement the Blood Pressure Measurement parser (pure functions + class)
  - Create `adapters/bp_parser.py` with pure functions: `parse_bp_flags`, `decode_sfloat` (IEEE-11073
    16-bit; reserved NaN/NRes mantissas → unusable), `required_length`, `kpa_to_mmhg`,
    `decode_timestamp` (7-byte date-time interpreted as host local time, returned tz-aware).
  - Implement `BloodPressureMeasurementParser(GattCharacteristicParser)`: decode flags; length-check
    (`None` if short); decode systolic@1 / diastolic@3 SFLOATs (`None` if reserved/unusable); normalize
    kPa→mmHg when the unit bit is set; set `effective` from the decoded local-aware timestamp when
    present, else injectable `now()` (local-aware); return `BloodPressure`. MAP decoded for length but
    discarded.
  - Unit tests: SFLOAT decode incl. reserved values; flags; `required_length`; kPa normalization;
    timestamp decode; `parse()` for mmHg, kPa, timestamp-present (store-and-forward), and short/
    malformed → `None`. Hypothesis round-trips for SFLOAT where practical.
  - _Requirements: FR-HH-5, FR-HH-6, NFR-HH-4, NFR-HH-6_

- [x] 5. Add the protocol citation in `docs/`
  - Create `docs/protocol-blood-pressure-measurement.md` citing the Bluetooth SIG Blood Pressure
    Service / Blood Pressure Measurement (`0x2A35`) specification (name, version, URL/date) and the
    IEEE-11073 SFLOAT reference used by the parser. Note the local-time timestamp assumption.
  - Add a compatibility row for standard-profile BP cuffs to `docs/device-compatibility.md`.
  - _Requirements: FR-HH-5, NFR-HH-4_

- [x] 6. Implement `ComponentVitalMapper` and register it
  - Replace the `NotImplementedError` body in `fhir/mappers.py` `ComponentVitalMapper.to_observation`
    with a real implementation: panel `code` from the vital's `loinc_code`, one `component[]` entry
    per `component_values()` pair (component LOINC + `valueQuantity` with UCUM), no panel-level
    `valueQuantity`; set `status`, `category`, `subject`, `device`, `effectiveDateTime`, `issued`,
    v4 `id`, `meta.profile`. Build via `Observation.model_validate`. Reuse existing module constants.
  - Register `ComponentVitalMapper` for `ComponentVital` in `fhir/__init__.py`.
  - Unit tests: valid US Core BP Observation (validated by `fhir.resources`), values only in
    `component[]`; `resolve_mapper(BloodPressure)` → `ComponentVitalMapper`, `resolve_mapper(HeartRate)`
    → `ScalarVitalMapper` (scalar resolution unchanged).
  - _Requirements: FR-HH-3, FR-HH-8, NFR-HH-3, NFR-HH-1_

- [x] 7. Add `ComponentRangeValidator` and generalize `DuplicateValidator`
  - Add `ComponentRangeValidator(Validator)` to `validation/builtin/validators.py`: checks each
    `component_values()` pair against an optional `{(vital_class, field_name): (min, max)}` override,
    else the `ComponentSpec.default_range`; rejection reason names the component and bounds, never the
    value; non-component vitals pass through.
  - Generalize `DuplicateValidator` identity: `ScalarVital` keeps `(device_id, effective, value)`;
    `ComponentVital` uses `(device_id, effective, component_values())`; other shapes pass through.
  - Export `ComponentRangeValidator` from `validation/__init__.py` under `# Concrete defaults`.
  - Unit tests: component range accept/reject per component, no value in reason, non-component
    pass-through; duplicate BP rejected on second identical reading; distinct BP readings accepted.
  - _Requirements: FR-HH-7, FR-HH-6, NFR-HH-5_

- [x] 8. Add `VOF_BP_*` configuration
  - Add `bp_systolic_min/max` (50/250) and `bp_diastolic_min/max` (30/150) to `Settings` in `config.py`.
  - Add the four `VOF_BP_*` variables with comments to `.env.example`.
  - Unit tests: `VOF_BP_*` load and defaults; `extra="forbid"` still rejects unknown vars.
  - _Requirements: FR-HH-7_

- [x] 9. Add `BloodPressureBleAdapter` and `MockBloodPressureAdapter`
  - Create `adapters/builtin/blood_pressure_ble.py`: `BloodPressureBleAdapter(DeviceAdapter)` composing
    a `BleConnection` for BP service `0x1810` / characteristic `0x2A35` with a
    `BloodPressureMeasurementParser` factory; implement `device_info`, `matches` (name substring),
    and delegate `state`/`connect`/`disconnect`/`vitals`. `bleak` only inside `BleConnection`.
  - Add `MockBloodPressureAdapter` + `BloodPressureEmissionMode` (VALID, IMPLAUSIBLE_SYSTOLIC,
    IMPLAUSIBLE_DIASTOLIC, STORE_AND_FORWARD) to `adapters/builtin/mock.py`; emits `BloodPressure`,
    never imports `bleak`; STORE_AND_FORWARD sets `effective` in the past.
  - Export both from `adapters/__init__.py` under `# Concrete defaults`.
  - Unit/contract tests: `MockBloodPressureAdapter` emission modes; `BloodPressureBleAdapter` satisfies
    the `DeviceAdapter` contract suite and `BleConnection` behavior (state transitions, drop-None,
    disconnect unblocks `vitals()`, and no-reading interval while connected is not a disconnection).
  - _Requirements: FR-HH-4, FR-HH-9, FR-HH-6, NFR-HH-5, NFR-HH-6_

- [x] 10. Wire blood pressure into the CLI
  - In `cli.py`: map `"bp"` → `BloodPressureBleAdapter`, `"mock-bp"` → `MockBloodPressureAdapter` in
    `_resolve_adapter`; in `_build_orchestrator` append `ComponentRangeValidator` built from the
    `VOF_BP_*` settings overrides to the `ValidatorChain` (after the scalar validators).
  - Confirm no orchestrator change is needed (per-vital `resolve_mapper` already dispatches).
  - Manual/scripted check: `uv run vitals-on-fhir --adapter mock-bp` produces BP Observations reaching
    the store and dashboard (no hardware). Do not add tests that depend on a running server.
  - _Requirements: FR-HH-9, FR-HH-3, FR-HH-8, NFR-HH-5_

- [x] 11. Full verification and changelog
  - Run `uv run ruff check .`, `uv run mypy src`, `uv run pytest` — all green, including
    `test_dependency_directions.py` and the unchanged HR suite.
  - Add a `CHANGELOG.md` entry (prepended) recording the blood-pressure slice: `BloodPressure` +
    `ComponentSpec`, `ComponentVitalMapper` activated, `BleConnection` extraction (note it preserves
    `BleHeartRateAdapter`'s surface), `BloodPressureMeasurementParser`, `ComponentRangeValidator` +
    generalized `DuplicateValidator`, `BloodPressureBleAdapter`/`MockBloodPressureAdapter`, `VOF_BP_*`,
    and the docs citation. Reference the requirement IDs. If any EviTrace-ported test pattern is used,
    record it in `NOTICE`.
  - _Requirements: NFR-HH-1, NFR-HH-2, NFR-HH-3, NFR-HH-4, NFR-HH-5, NFR-HH-6_
```
