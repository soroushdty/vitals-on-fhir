# Implementation Plan

**Spec: weight-body-mass** (weight scale — fourth and final phase-2 slice)

Each task is small, verifiable, and traces to requirements. Unlike the temperature slice, this slice
touches **no shared decoder module**: the weight value is a unit-scaled uint16 (new pure function local
to the weight parser, not `adapters/sfloat.py`), and the optional timestamp reuses the existing shared
`adapters/datetime_field.decode_timestamp` unchanged. So there is no "additive shared-module first"
guardrail task; the order is simply the new domain type, then the parser and its scaler, then docs,
config, adapters, CLI wiring, tests, the final config-surface checkpoint, and full verification. After
every task run `uv run ruff check .`, `uv run mypy src`, and `uv run pytest`; the existing heart-rate,
blood-pressure, oxygen-saturation, and body-temperature suites plus `tests/test_dependency_directions.py`
must stay green throughout (NFR-WT-1, NFR-WT-2, NFR-WT-6). Every new source file starts with
`# SPDX-License-Identifier: AGPL-3.0-or-later` (NFR-WT-4). Test sub-tasks are marked `*` (optional); the
design has a Correctness Properties section, so Properties 1–5 are implemented as single Hypothesis
property tests (≥100 iterations, tagged with the design property) placed next to the code they cover
(design §Testing Strategy).

- [x] 1. Add the `BodyWeight` vital-sign type
  - Create `vitals/builtin/body_weight.py`: frozen `BodyWeight(ScalarVital)` with
    `loinc_code="29463-7"`, `ucum_unit="kg"`, US Core Body Weight `us_core_profile`, and
    `plausible_range=(2.0, 650.0)` (physical-plausibility bounds, not clinical thresholds). No new
    instance fields (the device user-ID/BMI/height fields are not modelled).
  - Export from `vitals/__init__.py` under `# Concrete defaults`. Introduce no change to any existing
    public ABC signature or exported name.
  - _Design: §1. Requirements: FR-WT-1, NFR-WT-1, NFR-WT-3_

  - [x]* 1.1 Metadata tests for `BodyWeight`
    - `__init_subclass__` accepts the complete class; a deliberately incomplete local subclass raises at
      import time; instances are frozen; metadata present and correct (`29463-7`, `kg`, US Core Body
      Weight, `(2.0, 650.0)`).
    - _Design: §1. Requirements: FR-WT-1, NFR-WT-6_

- [x] 2. Implement the Weight Measurement parser (pure functions + class)
  - Create `adapters/weight_parser.py` with pure functions: `parse_weight_flags(byte) -> WeightFlags`
    (bits 0 unit, 1 timestamp-present, 2 user-ID-present, 3 BMI-and-height-present),
    `required_length(flags) -> int` (1 flags + weight uint16(2) + optional timestamp(7) + optional
    user-ID(1) + optional BMI+height(4)), and `scale_weight(raw, *, imperial) -> float` — SI
    `raw × 0.005` kg, Imperial `raw × 0.01 × 0.45359237` kg. The unit is chosen from the flags byte,
    never inferred from the value; the two multipliers are deliberately kept in one function so the
    SI/Imperial branch cannot be split or mis-ordered.
  - Implement `WeightMeasurementParser(GattCharacteristicParser)`: length-check (`None` if short);
    read the weight uint16 at offset 1 and scale via `scale_weight` using the unit flag; when the
    timestamp flag is set, decode via the shared `adapters.datetime_field.decode_timestamp` (`None` on
    invalid calendar date) and use it as `effective`, else `effective = self._now()` (injectable,
    tz-aware local default); construct `BodyWeight`. The user-ID, BMI, and height fields are
    length-accounted only, never decoded into the Reading — and per NFR-WT-5 the user ID is never
    decoded, logged, or stored.
  - Malformed/short/invalid-timestamp → `None`; the adapter drops it, logging at `DEBUG` with byte
    length only, never the value.
  - Do **not** modify `adapters/sfloat.py` (weight is not an IEEE-11073 float) or
    `adapters/datetime_field.py` (reused unchanged).
  - _Design: §2, §3. Requirements: FR-WT-2, FR-WT-3, NFR-WT-1, NFR-WT-4, NFR-WT-5, NFR-WT-6_

  - [x]* 2.1 Pure-function unit tests
    - `parse_weight_flags` bit decode; `required_length` across every optional-field combination;
      `scale_weight` on known SI and Imperial pairs (e.g. raw 14000 SI → 70.0 kg; a known lb pair →
      its kg equivalent).
    - _Design: §2, §3. Requirements: FR-WT-2, FR-WT-3, NFR-WT-6_

  - [x]* 2.2 Property test — unit-scaling correctness
    - **Property 1: Unit-scaling correctness** — for any raw uint16 and either unit flag,
      `scale_weight` returns `raw × 0.005` (SI) or `raw × 0.01 × 0.45359237` (Imperial) in kilograms,
      and the SI and Imperial results for the same raw value differ. Hypothesis, ≥100 iterations,
      tagged `# Feature: weight-body-mass, Property 1: Unit-scaling correctness`.
    - _Design: §2, Property 1. Requirements: FR-WT-2, NFR-WT-6_

  - [x]* 2.3 Property test — parser never crashes on arbitrary bytes
    - **Property 2: Parser never crashes on arbitrary bytes** — for any `bytes`, `parse` returns a
      `BodyWeight` or `None`, never raises. Hypothesis, ≥100 iterations, tagged
      `# Feature: weight-body-mass, Property 2: Parser never crashes on arbitrary bytes`.
    - Edge-case examples: truncated payload, invalid-calendar-date timestamp payload, and
      short-with-user-ID/BMI-present → all `None`.
    - _Design: §3, Property 2. Requirements: FR-WT-3, NFR-WT-6_

  - [x]* 2.4 Property test — well-formed build→parse round-trip
    - **Property 3: Well-formed payload build → parse round-trip** — for any generated kilogram value
      (within representable resolution) and any optional-field flag combination, a built payload parses
      back to a `BodyWeight` whose `value` equals the source within tolerance; when the timestamp flag
      is set to a generated valid date-time, `effective` equals that date-time host-local, tz-aware.
      Uses a pinned injected clock for the timestamp-absent branch. Hypothesis, ≥100 iterations, tagged
      `# Feature: weight-body-mass, Property 3: Well-formed payload build → parse round-trip`.
    - _Design: §3, Property 3. Requirements: FR-WT-3, NFR-WT-6_

  - [x]* 2.5 Property test — Imperial normalization correctness
    - **Property 4: Imperial normalization correctness** — for any generated kilogram value, an
      Imperial-flagged payload encoding the equivalent raw pounds and an SI-flagged payload encoding the
      equivalent raw kilograms parse to `value` results equal within tolerance (both `≈ C`).
      Hypothesis, ≥100 iterations, tagged
      `# Feature: weight-body-mass, Property 4: Imperial normalization correctness`.
    - _Design: §2, §3, Property 4. Requirements: FR-WT-2, FR-WT-3, NFR-WT-6_

- [x] 3. Add the protocol citation and device-compatibility row in `docs/`
  - Create `docs/protocol-weight-measurement.md` citing the Bluetooth SIG Weight Scale Service
    (`0x181D`) / Weight Measurement characteristic (`0x2A9D`), the GATT Specification Supplement (flags
    byte, uint16 weight field, SI vs Imperial resolution, optional timestamp/user-ID/BMI-height fields
    and offsets), and Assigned Numbers — each with name, version, and URL/date. State the SI (`0.005`
    kg) vs Imperial (`0.01` lb → kg) resolution rule and the pound→kilogram normalization, the
    host-local tz-aware timestamp convention (reference the blood-pressure doc), the decision not to
    model the user-ID/BMI/height fields (and that the user ID is never decoded, logged, or stored, per
    NFR-WT-5), and that no code was copied from other projects; include the Bluetooth SIG trademark
    notice.
  - In the same doc, add a **range-rationale note** recording the evidence behind the `(2.0, 650.0)` kg
    physical-plausibility bounds (not clinical thresholds): upper bound just above the heaviest
    documented human weight (~635 kg), lower bound at the smallest realistic standing-scale reading and
    above a zero/empty-scale decode artifact. Paraphrase the sources; include inline URLs.
  - Add a compatibility row for standard-profile BLE weight scales to `docs/device-compatibility.md`.
  - _Design: §1, §11. Requirements: FR-WT-3, FR-WT-1, FR-WT-8, NFR-WT-4_

- [x] 4. Add `VOF_WEIGHT_*` configuration
  - Add `weight_min` (2.0) and `weight_max` (650.0) to `Settings` in `config.py`, with a comment noting
    the bounds are physical-plausibility, not clinical.
  - Add `VOF_WEIGHT_MIN` / `VOF_WEIGHT_MAX` with comments to `.env.example`.
  - _Design: §9. Requirements: FR-WT-6_

  - [x]* 4.1 Config unit tests
    - `VOF_WEIGHT_MIN` / `VOF_WEIGHT_MAX` load and defaults (2.0 / 650.0); `extra="forbid"` still
      rejects unknown vars.
    - _Design: §9. Requirements: FR-WT-6, NFR-WT-6_

- [x] 5. Add `WeightScaleBleAdapter` and `MockWeightAdapter`
  - Create `adapters/builtin/weight_scale_ble.py`: `WeightScaleBleAdapter(DeviceAdapter)` composing a
    `BleConnection` for WSS service `0x181D` / characteristic `0x2A9D` with a `WeightMeasurementParser`
    factory; implement `device_info`, `matches` (returns `True`; service-UUID scan is authoritative),
    and delegate `state`/`connect`/`disconnect`/`vitals`. Parser import lazy inside `_build_parser`;
    `bleak` only inside `BleConnection` (reused unchanged — bleak handles indications transparently,
    design §5).
  - Add `MockWeightAdapter` + `WeightEmissionMode` (VALID, IMPLAUSIBLE, IMPERIAL_SOURCE) to
    `adapters/builtin/mock.py`; emits `BodyWeight` (always kilograms; IMPERIAL_SOURCE emits the
    already-normalized kilogram equivalent), never imports `bleak`.
  - Export `WeightScaleBleAdapter`, `MockWeightAdapter`, and `WeightEmissionMode` from
    `adapters/__init__.py` under `# Concrete defaults`.
  - _Design: §4, §5, §6. Requirements: FR-WT-4, FR-WT-8, NFR-WT-1, NFR-WT-4, NFR-WT-5_

  - [x]* 5.1 Mock + adapter contract/behavior tests
    - `MockWeightAdapter` emission modes (VALID / IMPLAUSIBLE / IMPERIAL_SOURCE) and
      never-imports-`bleak` (AST check); `WeightScaleBleAdapter` satisfies the reusable `DeviceAdapter`
      contract suite and the `BleConnection` behavior (state transitions, drop-`None`, disconnect
      unblocks `vitals()`, a quiet interval while connected is not a disconnection).
    - _Design: §4, §5, §6. Requirements: FR-WT-4, FR-WT-8, NFR-WT-6_

- [x] 6. Wire body weight into the CLI
  - In `cli.py` `_resolve_adapter`: map `"weight"` → `WeightScaleBleAdapter(device_name=...)` and
    `"mock-weight"` → `MockWeightAdapter()`, alongside the existing `mock`, `mock-bp`, `mock-spo2`,
    `mock-temp`, `miband10`, `bp`, `spo2`, `temp` names; update the `--adapter` help text and the
    `ValueError`/argparse strings to list the new names. Import `BodyWeight` from `vitals` and the two
    new adapters from `adapters`.
  - In `_build_orchestrator`, add the `BodyWeight: (settings.weight_min, settings.weight_max)` entry to
    the `PlausibleRangeValidator` `scalar_overrides` map (no validator code change; `DuplicateValidator`
    and `SensorContactValidator` unchanged). Confirm no orchestrator change is needed (per-vital
    `resolve_mapper` already dispatches `BodyWeight → ScalarVitalMapper`).
  - Scripted no-server check: `uv run vitals-on-fhir --adapter mock-weight` produces weight
    Observations reaching the store/dashboard (no hardware). Do not add tests that depend on a running
    server.
  - _Design: §7, §8, §10. Requirements: FR-WT-8, FR-WT-6, FR-WT-5, NFR-WT-5_

  - [x]* 6.1 Validation wiring tests
    - **Property 5: Per-class bounds applied with no cross-application** — for any overrides map and any
      scalar reading, the bounds applied are exactly that reading's own class bounds; accepted iff in
      range; a weight override never changes a non-weight reading's decision. Hypothesis, ≥100
      iterations, tagged `# Feature: weight-body-mass, Property 5: Per-class bounds applied with no cross-application`.
    - Example tests: `VOF_WEIGHT_*` bounds apply to `BodyWeight` and not to HR/SpO2/temperature and
      vice versa; rejection reason names bounds only, never the value; a `BodyWeight` duplicate on
      `(device_id, effective, value)` is rejected.
    - _Design: §7, Property 5. Requirements: FR-WT-6, NFR-WT-5, NFR-WT-6_

  - [x]* 6.2 Mapper + API tests
    - `resolve_mapper(BodyWeight) → ScalarVitalMapper`; the built Observation validates as US Core Body
      Weight with `value`, UCUM `code` `kg`, LOINC `29463-7`; `HeartRate`/`OxygenSaturation`/
      `BodyTemperature` → `ScalarVitalMapper` and `BloodPressure → ComponentVitalMapper` resolution
      unchanged. Search by `code=29463-7` returns weight Observations; CapabilityStatement reflects
      searchability; no write operation.
    - _Design: §8, §11. Requirements: FR-WT-5, FR-WT-7, NFR-WT-3, NFR-WT-6_

- [x] 7. Update the config-surface checkpoint (final phase-2 checkpoint)
  - Update `docs/brief-config-file.md`: add the "Checkpoint — after body weight" subsection recording
    that the counted `VOF_*` surface reaches **19** (12 per-vital range keys) after `VOF_WEIGHT_*`, with
    an explicit "awkward?" judgment. As body weight is the final phase-2 vital, close the phase-2
    length-driver assessment and give the recommendation (promote the `config.yaml` idea to its own
    spec, or leave it idea-only) with the completed range-key surface in front of it. Records count +
    judgment only; builds no config layer, consistent with the brief's guardrails.
  - _Design: §11. Requirements: FR-WT-9, FR-WT-6 (context), NFR-WT-4_

- [x] 8. Full verification, changelog, and dependency-direction check
  - Run `uv run ruff check .`, `uv run mypy src`, and `uv run pytest` — all green, including
    `tests/test_dependency_directions.py` and the unchanged HR, BP, SpO2, and temperature suites.
  - Prepend a `CHANGELOG.md` entry recording the body-weight slice: `BodyWeight` (scalar, US Core Body
    Weight, `(2.0, 650.0)` kg physical-plausibility bounds), the unit-scaled uint16 `scale_weight`
    (SI `0.005` kg vs Imperial `0.01` lb→kg — noting it does **not** touch `adapters/sfloat.py`),
    `WeightMeasurementParser` (reusing the shared `decode_timestamp`),
    `WeightScaleBleAdapter`/`MockWeightAdapter`, `VOF_WEIGHT_*`, the `weight` / `mock-weight` short
    names, the new protocol doc, and the final phase-2 `brief-config-file.md` checkpoint. Reference the
    FR-WT-*/NFR-WT-* IDs. Note that this slice completes the phase-2 vital-sign set. If any
    EviTrace-ported test pattern is used, record it in `NOTICE`.
  - _Design: §11. Requirements: NFR-WT-1, NFR-WT-2, NFR-WT-3, NFR-WT-4, NFR-WT-5, NFR-WT-6_

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster path; core
  implementation sub-tasks are never marked optional.
- Each task references the FR-WT-*/NFR-WT-* requirements it satisfies and the design section(s) that
  specify it, for traceability toward the planned preprint.
- Unlike the temperature slice, no shared decoder module changes: the weight scaler is a new local pure
  function (not `adapters/sfloat.py`) and the timestamp decode is reused unchanged from
  `adapters/datetime_field.py`. The regression guardrail is confirming those shared modules stay
  untouched.
- Property tests implement the five design Correctness Properties, one Hypothesis test each, ≥100
  iterations, tagged with the design property (design §Testing Strategy).
- The checkpoint update (task 7) builds no code and changes no behavior; it is an idea-only record and
  closes the phase-2 config-surface assessment.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "2", "3"] },
    { "id": 1, "tasks": ["1.1", "2.1", "2.2", "2.3", "2.4", "2.5", "4"] },
    { "id": 2, "tasks": ["4.1", "5"] },
    { "id": 3, "tasks": ["5.1", "6"] },
    { "id": 4, "tasks": ["6.1", "6.2", "7"] },
    { "id": 5, "tasks": ["8"] }
  ]
}
```
