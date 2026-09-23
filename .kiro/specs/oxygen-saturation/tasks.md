# Implementation Plan

**Spec: oxygen-saturation** (pulse oximetry — second phase-2 slice)

Each task is small, verifiable, and traces to requirements. Order minimizes regression risk: the
behavior-preserving SFLOAT extraction and the backward-compatible validator generalization come first
(guarded by the existing suite), then the new domain type, parser, adapter, config, wiring, and docs.
After every task run `uv run ruff check .`, `uv run mypy src`, and `uv run pytest`; the existing
heart-rate and blood-pressure suites plus `tests/test_dependency_directions.py` must stay green
throughout (NFR-SPO2-1, NFR-SPO2-2, NFR-SPO2-6). Every new source file starts with
`# SPDX-License-Identifier: AGPL-3.0-or-later` (NFR-SPO2-4).

- [x] 1. Extract SFLOAT decoding into a shared module (behavior-preserving)
  - Create `adapters/sfloat.py` with pure `decode_sfloat(data, offset) -> float | None`, the
    `_SFLOAT_RESERVED_MANTISSAS` set, and an exported `SFLOAT_SIZE` constant, moved verbatim in
    behavior from `bp_parser.py`. Header cites IEEE-11073-20601.
  - Refactor `adapters/bp_parser.py` to import `decode_sfloat` (and the size constant) from
    `adapters.sfloat` instead of defining them; keep BP offsets and all other logic identical.
  - Verify: the full existing suite (esp. BP SFLOAT tests) and `test_dependency_directions.py` pass
    unchanged — this is the extraction guardrail.
  - Unit tests: `sfloat` decode for normal values, negative exponent/mantissa, and each reserved
    mantissa → `None`; a Hypothesis round-trip where practical.
  - _Requirements: FR-SPO2-2, NFR-SPO2-2, NFR-SPO2-6_

- [x] 2. Generalize `PlausibleRangeValidator` to per-vital-class bounds (backward compatible)
  - Add an `overrides: dict[type, tuple[float, float]] | None` keyword arg; look up
    `overrides[type(vital)]` else `vital.plausible_range`. Retain the `(hr_min, hr_max)` positional
    form by mapping it internally to `{HeartRate: (hr_min, hr_max)}` (lazy `HeartRate` import inside
    `__init__`). Rejection reason names bounds only, never the value.
  - Verify existing `PlausibleRangeValidator` tests pass unchanged (back-compat guardrail).
  - Unit tests: an SpO2 override applies to SpO2 and not to HR, and vice versa (cross-application
    guard); no-override falls back to `plausible_range`; legacy positional construction unchanged.
  - _Requirements: FR-SPO2-6, NFR-SPO2-1, NFR-SPO2-5_

- [x] 3. Add the `OxygenSaturation` vital-sign type
  - Create `vitals/builtin/oxygen_saturation.py`: frozen `OxygenSaturation(ScalarVital)` with
    `loinc_code="59408-5"`, `ucum_unit="%"`, US Core Pulse Oximetry `us_core_profile`, and
    `plausible_range=(70.0, 100.0)`.
  - Export from `vitals/__init__.py` under `# Concrete defaults`.
  - Unit tests: `__init_subclass__` accepts the complete class; a deliberately incomplete local
    subclass raises; instances are frozen; metadata present and correct.
  - _Requirements: FR-SPO2-1, NFR-SPO2-1_

- [x] 4. Implement the PLX Continuous Measurement parser (pure functions + class)
  - Create `adapters/plx_parser.py` with pure `parse_plx_flags(byte) -> PlxFlags` and
    `required_length(flags) -> int` (flags byte + mandatory SpO2/PR SFLOAT pair + optional fast/slow
    pairs, measurement-status, device-and-sensor-status, and pulse-amplitude-index sizes per flags).
  - Implement `PlxContinuousMeasurementParser(GattCharacteristicParser)`: length-check (`None` if
    short); decode SpO2 SFLOAT at offset 1 via `adapters.sfloat.decode_sfloat` (`None` if
    reserved/unusable); set `effective` from injectable `now()` (tz-aware, defaults to
    `datetime.now(UTC)`); return `OxygenSaturation`. Pulse rate and optional fields are
    length-accounted but not decoded into the Reading.
  - Unit tests: flags decode; `required_length` across optional-field combinations; `parse()` for
    well-formed SpO2, optional-fields-present, and short/reserved-SFLOAT → `None`.
  - _Requirements: FR-SPO2-3, FR-SPO2-2, NFR-SPO2-4, NFR-SPO2-5, NFR-SPO2-6_

- [x] 5. Add the protocol citation in `docs/`
  - Create `docs/protocol-pulse-oximeter-measurement.md` citing the Bluetooth SIG Pulse Oximeter
    Service / PLX Continuous Measurement (`0x2A5F`) specification (name, version, URL/date), the PLX
    profile, Assigned Numbers for `0x1822`/`0x2A5F`, and the IEEE-11073 SFLOAT reference. Note that the
    continuous characteristic carries no timestamp (so `effective = now()`), and that spot-check
    `0x2A5E` is deferred.
  - Add a compatibility row for standard-profile pulse oximeters to `docs/device-compatibility.md`.
  - _Requirements: FR-SPO2-3, NFR-SPO2-4_

- [x] 6. Use `ucum_unit` for the scalar `valueQuantity.unit` display
  - In `fhir/mappers.py`, change `ScalarVitalMapper` to set `valueQuantity.unit` from the vital's
    `ucum_unit` (removing the HR-specific `_VALUE_UNIT_DISPLAY = "beats/minute"` constant) so SpO2
    reads `%`; `code` stays the authoritative UCUM code. No other mapper change; no registration
    change (`OxygenSaturation` resolves to `ScalarVitalMapper` via the existing MRO registry).
  - Update the existing HR mapper test asserting the unit display (`"beats/minute"` → `"/min"`).
  - Unit tests: `resolve_mapper(OxygenSaturation)` → `ScalarVitalMapper`; the built Observation
    validates as US Core Pulse Oximetry with `value`, UCUM `code` `%`, LOINC `59408-5`;
    `HeartRate → ScalarVitalMapper` and `BloodPressure → ComponentVitalMapper` resolution unchanged.
  - _Requirements: FR-SPO2-5, NFR-SPO2-3, NFR-SPO2-1_

- [x] 7. Add `VOF_SPO2_*` configuration
  - Add `spo2_min` (70.0) and `spo2_max` (100.0) to `Settings` in `config.py`.
  - Add `VOF_SPO2_MIN` / `VOF_SPO2_MAX` with comments to `.env.example`.
  - Unit tests: `VOF_SPO2_*` load and defaults; `extra="forbid"` still rejects unknown vars.
  - _Requirements: FR-SPO2-6_

- [x] 8. Add `PulseOximeterBleAdapter` and `MockOximeterAdapter`
  - Create `adapters/builtin/pulse_oximeter_ble.py`: `PulseOximeterBleAdapter(DeviceAdapter)` composing
    a `BleConnection` for PLX service `0x1822` / characteristic `0x2A5F` with a
    `PlxContinuousMeasurementParser` factory; implement `device_info`, `matches` (returns `True`;
    service-UUID scan is authoritative), and delegate `state`/`connect`/`disconnect`/`vitals`. Parser
    import lazy inside `_build_parser`; `bleak` only inside `BleConnection`.
  - Add `MockOximeterAdapter` + `OximeterEmissionMode` (VALID, IMPLAUSIBLE) to
    `adapters/builtin/mock.py`; emits `OxygenSaturation`, never imports `bleak`.
  - Export both from `adapters/__init__.py` under `# Concrete defaults`.
  - Unit/contract tests: `MockOximeterAdapter` emission modes; `PulseOximeterBleAdapter` satisfies the
    `DeviceAdapter` contract suite and `BleConnection` behavior (state transitions, drop-None,
    disconnect unblocks `vitals()`, and a no-reading interval while connected is not a disconnection).
  - _Requirements: FR-SPO2-4, FR-SPO2-8, NFR-SPO2-5, NFR-SPO2-6_

- [x] 9. Wire oxygen saturation into the CLI
  - In `cli.py`: map `"spo2"` → `PulseOximeterBleAdapter(device_name=...)` and `"mock-spo2"` →
    `MockOximeterAdapter` in `_resolve_adapter`; update the `--adapter` help and error strings to list
    the new names. In `_build_orchestrator`, build `PlausibleRangeValidator(overrides={HeartRate: (hr
    bounds), OxygenSaturation: (spo2 bounds)})`, replacing the current positional HR construction.
  - Confirm no orchestrator change is needed (per-vital `resolve_mapper` already dispatches).
  - Manual/scripted check: `uv run vitals-on-fhir --adapter mock-spo2` produces SpO2 Observations
    reaching the store and dashboard (no hardware). Do not add tests that depend on a running server.
  - _Requirements: FR-SPO2-8, FR-SPO2-5, FR-SPO2-6, NFR-SPO2-5_

- [x] 10. Full verification, docs, and changelog
  - Run `uv run ruff check .`, `uv run mypy src`, `uv run pytest` — all green, including
    `test_dependency_directions.py` and the unchanged HR and BP suites.
  - Update the surface-size checkpoint in `docs/brief-config-file.md` with the new `VOF_*` count after
    `VOF_SPO2_*` lands, and re-state whether the flat list has crossed "awkward".
  - Add a `CHANGELOG.md` entry (prepended) recording the SpO2 slice: `OxygenSaturation` (scalar, US
    Core Pulse Oximetry), shared `adapters/sfloat.py` (note the behavior-preserving BP-parser
    refactor), `PlxContinuousMeasurementParser`, `PulseOximeterBleAdapter`/`MockOximeterAdapter`,
    per-class `PlausibleRangeValidator` generalization, `VOF_SPO2_*`, the docs citation, and the HR
    `valueQuantity.unit` display change (`"beats/minute"` → `"/min"`, non-breaking). Reference the
    requirement IDs. If any EviTrace-ported test pattern is used, record it in `NOTICE`.
  - _Requirements: NFR-SPO2-1, NFR-SPO2-2, NFR-SPO2-3, NFR-SPO2-4, NFR-SPO2-5, NFR-SPO2-6_
