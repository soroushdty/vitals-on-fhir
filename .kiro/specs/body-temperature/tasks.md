# Implementation Plan

**Spec: body-temperature** (health thermometer — third phase-2 slice)

Each task is small, verifiable, and traces to requirements. Order minimizes regression risk: the two
behavior-preserving/additive shared-module changes (adding `decode_float`, extracting
`decode_timestamp`) come first, each guarded by the existing suite, then the new domain type, parser,
protocol docs, config, adapters, CLI wiring, the idea-only briefs, and full verification. After every
task run `uv run ruff check .`, `uv run mypy src`, and `uv run pytest`; the existing heart-rate,
blood-pressure, and oxygen-saturation suites plus `tests/test_dependency_directions.py` must stay
green throughout (NFR-TEMP-1, NFR-TEMP-2, NFR-TEMP-6). Every new source file starts with
`# SPDX-License-Identifier: AGPL-3.0-or-later` (NFR-TEMP-4). Test sub-tasks are marked `*` (optional);
the design has a Correctness Properties section, so Properties 1–5 are implemented as single
Hypothesis property tests (≥100 iterations, tagged with the design property) placed next to the code
they cover (design §Testing Strategy).

- [x] 1. Add IEEE-11073 32-bit FLOAT decoding to the shared module (additive)
  - In `adapters/sfloat.py`, add a pure `decode_float(data, offset) -> float | None`: mask the 24-bit
    mantissa and 8-bit exponent from the little-endian 4-byte word, reject the FLOAT reserved mantissa
    values (`0x007FFFFF` NaN, `0x00800000` NRes, `0x007FFFFE` +INF, `0x00800002` −INF, `0x00800001`
    reserved) by returning `None`, sign-extend the 24-bit mantissa and 8-bit exponent, and return
    `mantissa × 10^exponent`. Add a `FLOAT_SIZE = 4` constant and the `_FLOAT_RESERVED_MANTISSAS` set.
  - Leave `decode_sfloat`, its signature, its reserved set, and `SFLOAT_SIZE` **unchanged** (additive
    only). The module header already cites IEEE-11073-20601, which defines both encodings.
  - Verify: the full existing suite (esp. the SFLOAT/BP/SpO2 decoder tests) and
    `test_dependency_directions.py` pass unchanged — this is the additive-change guardrail.
  - _Design: §2. Requirements: FR-TEMP-2, NFR-TEMP-1, NFR-TEMP-2_

  - [x] 1.1 Property + edge-case tests for `decode_float`
    - **Property 1: FLOAT decode round-trip** — for any signed 24-bit mantissa and signed 8-bit
      exponent packed little-endian (avoiding the reserved mantissas), `decode_float` returns
      `mantissa × 10^exponent` within tolerance, with correct signs. Hypothesis, ≥100 iterations,
      tagged `# Feature: body-temperature, Property 1: FLOAT decode round-trip`.
    - Edge-case examples: each of the five FLOAT reserved mantissas → `None`; a negative-exponent and a
      negative-mantissa example decode correctly. Kept **separate** from the SFLOAT decoder tests.
    - _Design: §2, Property 1. Requirements: FR-TEMP-2, NFR-TEMP-6_

- [x] 2. Extract `decode_timestamp` into a shared `adapters` helper (behavior-preserving)
  - Create `adapters/datetime_field.py` holding the org.bluetooth 7-byte date-time decode:
    `decode_timestamp(data, offset) -> datetime | None` (interpret the zoneless value as host local
    time, return timezone-aware, return `None` on an invalid/zero calendar date) and a
    `TIMESTAMP_SIZE = 7` constant, moved verbatim in behavior from `bp_parser.py`.
  - Refactor `adapters/bp_parser.py` to import `decode_timestamp` (and the size constant) from
    `adapters.datetime_field` and **re-export** `decode_timestamp` so its existing `__all__` and tests
    stay green (behavior-preserving, additive — decision 6 / extract-and-share, user approved).
  - Verify: the full existing BP suite (esp. its timestamp tests) and `test_dependency_directions.py`
    pass unchanged — this is the extraction guardrail. This is an intra-`adapters` move, so dependency
    directions are unaffected.
  - _Design: §3 (recommendation, decision 6). Requirements: FR-TEMP-3, NFR-TEMP-1, NFR-TEMP-2_

- [x] 3. Add the `BodyTemperature` vital-sign type
  - Create `vitals/builtin/body_temperature.py`: frozen `BodyTemperature(ScalarVital)` with
    `loinc_code="8310-5"`, `ucum_unit="Cel"`, US Core Body Temperature `us_core_profile`, and
    `plausible_range=(10.0, 47.0)` (physical-plausibility bounds, not clinical thresholds). No new
    instance fields (the device temperature-type field is not modelled).
  - Export from `vitals/__init__.py` under `# Concrete defaults`. Introduce no change to any existing
    public ABC signature or exported name.
  - _Design: §1. Requirements: FR-TEMP-1, NFR-TEMP-1, NFR-TEMP-3_

  - [x] 3.1 Metadata tests for `BodyTemperature`
    - `__init_subclass__` accepts the complete class; a deliberately incomplete local subclass raises
      at import time; instances are frozen; metadata present and correct (`8310-5`, `Cel`, US Core
      Body Temperature, `(10.0, 47.0)`).
    - _Design: §1. Requirements: FR-TEMP-1, NFR-TEMP-6_

- [x] 4. Implement the Temperature Measurement parser (pure functions + class)
  - Create `adapters/temp_parser.py` with pure functions: `parse_temp_flags(byte) -> TempFlags`
    (bits 0 unit, 1 timestamp-present, 2 temperature-type-present), `required_length(flags) -> int`
    (1 flags + FLOAT(4) + optional timestamp(7) + optional type(1)), and
    `fahrenheit_to_celsius(value) -> float` = `(value - 32) * 5 / 9`.
  - Implement `TemperatureMeasurementParser(GattCharacteristicParser)`: length-check (`None` if short);
    decode the temperature 32-bit FLOAT at offset 1 via `adapters.sfloat.decode_float` (`None` if
    reserved/unusable); when the unit flag is set, normalize Fahrenheit→Celsius; when the timestamp
    flag is set, decode via the shared `adapters.datetime_field.decode_timestamp` (`None` on invalid
    calendar date) and use it as `effective`, else `effective = self._now()` (injectable, tz-aware
    local default); construct `BodyTemperature`. The temperature-type field is length-accounted only,
    never decoded into the Reading.
  - Malformed/short/reserved-FLOAT/invalid-timestamp → `None`; the adapter drops it, logging at
    `DEBUG` with byte length only, never the value.
  - _Design: §3. Requirements: FR-TEMP-3, FR-TEMP-2, NFR-TEMP-4, NFR-TEMP-5, NFR-TEMP-6_

  - [x] 4.1 Pure-function unit tests
    - `parse_temp_flags` bit decode; `required_length` across every optional-field combination;
      `fahrenheit_to_celsius` on known pairs (e.g. 98.6 °F → 37.0 °C).
    - _Design: §3. Requirements: FR-TEMP-3, NFR-TEMP-6_

  - [x] 4.2 Property test — parser never crashes on arbitrary bytes
    - **Property 2: Parser never crashes on arbitrary bytes** — for any `bytes`, `parse` returns a
      `BodyTemperature` or `None`, never raises. Hypothesis, ≥100 iterations, tagged
      `# Feature: body-temperature, Property 2: Parser never crashes on arbitrary bytes`.
    - Edge-case examples: truncated payload, reserved-FLOAT payload, invalid-calendar-date timestamp
      payload, and short-with-type-present → all `None`.
    - _Design: §3, Property 2. Requirements: FR-TEMP-3, NFR-TEMP-6_

  - [x] 4.3 Property test — well-formed build→parse round-trip
    - **Property 3: Well-formed payload build → parse round-trip** — for any generated Celsius value
      and any optional-field flag combination, a built payload parses back to a `BodyTemperature` whose
      `value` equals the source (within tolerance); when the timestamp flag is set to a generated valid
      date-time, `effective` equals that date-time as host-local, tz-aware. Uses a pinned injected
      clock for the timestamp-absent branch. Hypothesis, ≥100 iterations, tagged
      `# Feature: body-temperature, Property 3: Well-formed payload build → parse round-trip`.
    - _Design: §3, Property 3. Requirements: FR-TEMP-3, NFR-TEMP-6_

  - [x] 4.4 Property test — Fahrenheit normalization correctness
    - **Property 4: Fahrenheit normalization correctness** — for any generated value, a
      Fahrenheit-flagged payload encoding `C × 9/5 + 32` and a Celsius-flagged payload encoding `C`
      parse to `value` results equal within tolerance (both `≈ C`). Hypothesis, ≥100 iterations,
      tagged `# Feature: body-temperature, Property 4: Fahrenheit normalization correctness`.
    - _Design: §3, Property 4. Requirements: FR-TEMP-3, NFR-TEMP-6_

- [x] 5. Add the protocol citation and device-compatibility row in `docs/`
  - Create `docs/protocol-body-temperature-measurement.md` citing the Bluetooth SIG Health Thermometer
    Service (`0x1809`) / Temperature Measurement characteristic (`0x2A1C`), the GATT Specification
    Supplement (flags byte, FLOAT value field, optional timestamp and temperature-type fields,
    offsets), Assigned Numbers, and ISO/IEEE 11073-20601 (the 32-bit FLOAT encoding and its reserved
    values) — each with name, version, and URL/date. State the Fahrenheit→Celsius normalization, the
    host-local tz-aware timestamp convention (reference the blood-pressure doc), and that no code was
    copied from other projects; include the Bluetooth SIG trademark notice.
  - In the same doc, add a **range-rationale note** recording the evidence behind the `(10.0, 47.0)` °C
    physical-plausibility bounds (not clinical thresholds): lower bound below the lowest documented
    neurologically-intact accidental-hypothermia survival (~11.8 °C pediatric,
    https://pubmed.ncbi.nlm.nih.gov/33084865/; 13.7 °C adult / Anna Bågenholm,
    https://pubmed.ncbi.nlm.nih.gov/32482520/); upper bound just above the highest recorded heat-stroke
    survivor (46.5 °C, 1980 —
    https://www.guinnessworldrecords.com/world-records/67749-highest-body-temperature,
    https://en.wikipedia.org/wiki/Hyperthermia, https://pubmed.ncbi.nlm.nih.gov/7073052/). Paraphrase
    the sources; include the inline URLs.
  - Add a compatibility row for standard-profile BLE thermometers to `docs/device-compatibility.md`.
  - _Design: §Docs deliverables. Requirements: FR-TEMP-3, FR-TEMP-1, FR-TEMP-8, NFR-TEMP-4_

- [x] 6. Add `VOF_TEMP_*` configuration
  - Add `temp_min` (10.0) and `temp_max` (47.0) to `Settings` in `config.py`, with a comment noting the
    bounds are physical-plausibility, not clinical.
  - Add `VOF_TEMP_MIN` / `VOF_TEMP_MAX` with comments to `.env.example`.
  - _Design: §9. Requirements: FR-TEMP-6_

  - [x] 6.1 Config unit tests
    - `VOF_TEMP_MIN` / `VOF_TEMP_MAX` load and defaults (10.0 / 47.0); `extra="forbid"` still rejects
      unknown vars.
    - _Design: §9. Requirements: FR-TEMP-6, NFR-TEMP-6_

- [x] 7. Add `HealthThermometerBleAdapter` and `MockThermometerAdapter`
  - Create `adapters/builtin/thermometer_ble.py`: `HealthThermometerBleAdapter(DeviceAdapter)`
    composing a `BleConnection` for HTS service `0x1809` / characteristic `0x2A1C` with a
    `TemperatureMeasurementParser` factory; implement `device_info`, `matches` (returns `True`;
    service-UUID scan is authoritative), and delegate `state`/`connect`/`disconnect`/`vitals`. Parser
    import lazy inside `_build_parser`; `bleak` only inside `BleConnection` (reused unchanged — bleak
    handles indications transparently, design §5).
  - Add `MockThermometerAdapter` + `ThermometerEmissionMode` (VALID, IMPLAUSIBLE, FAHRENHEIT_SOURCE) to
    `adapters/builtin/mock.py`; emits `BodyTemperature` (always Celsius; FAHRENHEIT_SOURCE emits the
    already-normalized Celsius equivalent), never imports `bleak`.
  - Export both from `adapters/__init__.py` under `# Concrete defaults`.
  - _Design: §4, §5, §6. Requirements: FR-TEMP-4, FR-TEMP-8, NFR-TEMP-1, NFR-TEMP-4, NFR-TEMP-5_

  - [x] 7.1 Mock + adapter contract/behavior tests
    - `MockThermometerAdapter` emission modes (VALID / IMPLAUSIBLE / FAHRENHEIT_SOURCE) and
      never-imports-`bleak` (AST check); `HealthThermometerBleAdapter` satisfies the reusable
      `DeviceAdapter` contract suite and the `BleConnection` behavior (state transitions, drop-`None`,
      disconnect unblocks `vitals()`, a quiet interval while connected is not a disconnection).
    - _Design: §4, §5, §6. Requirements: FR-TEMP-4, FR-TEMP-8, NFR-TEMP-6_

- [x] 8. Wire body temperature into the CLI
  - In `cli.py` `_resolve_adapter`: map `"temp"` → `HealthThermometerBleAdapter(device_name=...)` and
    `"mock-temp"` → `MockThermometerAdapter()`, alongside the existing `mock`, `mock-bp`, `mock-spo2`,
    `miband10`, `bp`, `spo2` names; update the `--adapter` help text and the `ValueError`/argparse
    strings to list the new names.
  - In `_build_orchestrator`, add the `BodyTemperature: (settings.temp_min, settings.temp_max)` entry
    to the `PlausibleRangeValidator` `scalar_overrides` map (no validator code change; `DuplicateValidator`
    and `SensorContactValidator` unchanged). Confirm no orchestrator change is needed (per-vital
    `resolve_mapper` already dispatches `BodyTemperature → ScalarVitalMapper`).
  - Scripted no-server check: `uv run vitals-on-fhir --adapter mock-temp` produces temperature
    Observations reaching the store/dashboard (no hardware). Do not add tests that depend on a running
    server.
  - _Design: §7, §8, §10. Requirements: FR-TEMP-8, FR-TEMP-6, FR-TEMP-5, NFR-TEMP-5_

  - [x] 8.1 Validation wiring tests
    - **Property 5: Per-class bounds applied with no cross-application** — for any overrides map and any
      scalar reading, the bounds applied are exactly that reading's own class bounds; accepted iff in
      range; a temperature override never changes a non-temperature reading's decision. Hypothesis,
      ≥100 iterations, tagged `# Feature: body-temperature, Property 5: Per-class bounds applied with no cross-application`.
    - Example tests: `VOF_TEMP_*` bounds apply to `BodyTemperature` and not to HR/SpO2 and vice versa;
      rejection reason names bounds only, never the value; a `BodyTemperature` duplicate on
      `(device_id, effective, value)` is rejected.
    - _Design: §7, Property 5. Requirements: FR-TEMP-6, NFR-TEMP-5, NFR-TEMP-6_

  - [x] 8.2 Mapper + API tests
    - `resolve_mapper(BodyTemperature) → ScalarVitalMapper`; the built Observation validates as US Core
      Body Temperature with `value`, UCUM `code` `Cel`, LOINC `8310-5`; `HeartRate`/`OxygenSaturation`
      → `ScalarVitalMapper` and `BloodPressure → ComponentVitalMapper` resolution unchanged. Search by
      `code=8310-5` returns temperature Observations; CapabilityStatement reflects searchability; no
      write operation.
    - _Design: §8, §11. Requirements: FR-TEMP-5, FR-TEMP-7, NFR-TEMP-3, NFR-TEMP-6_

- [x] 9. Author the idea-only briefs and update the config-surface checkpoint
  - Create `docs/brief-validation-modes.md` (idea-only; SPDX header
    `<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->` as the first line; same "Status: Idea only"
    framing as `docs/brief-config-file.md`). Capture: the plausibility-vs-personal/clinical distinction;
    the user-approved decision that personal/clinical thresholds **flag** (e.g. FHIR `interpretation`)
    and **never drop**; the three options with honest tradeoffs (keyword modes; ±k·SD with default k=2,
    valid only as a flagging heuristic since it would drop ~5% of real readings at k=2; explicit
    per-person bounds); and the dependencies/guardrails (rides on structured config, likely needs
    phase-4 stored history, its own spec + CHANGELOG entry, plausibility bounds stay wide and
    physics-based).
  - Update `docs/brief-config-file.md`: add the "Checkpoint — after body temperature" subsection
    recording that the counted `VOF_*` surface reaches **17** (10 per-vital range keys) after
    `VOF_TEMP_*`, with an explicit "awkward?" judgment (records count + judgment only, builds no config
    layer); and add the short **structural-driver note** that per-vital validation modes (from
    brief-validation-modes) are a second, structural driver toward `config.yaml`, distinct from the
    flat-list-length driver, since modes/k-factors/keyword options do not express cleanly as flat
    `VOF_<VITAL>_<BOUND>` pairs.
  - _Design: §Docs deliverables. Requirements: FR-TEMP-9, FR-TEMP-6 (context), NFR-TEMP-4_

- [x] 10. Full verification, changelog, and dependency-direction check
  - Run `uv run ruff check .`, `uv run mypy src`, and `uv run pytest` — all green, including
    `tests/test_dependency_directions.py` and the unchanged HR, BP, and SpO2 suites.
  - Prepend a `CHANGELOG.md` entry recording the body-temperature slice: `BodyTemperature` (scalar, US
    Core Body Temperature, `(10.0, 47.0)` °C physical-plausibility bounds), `decode_float` (32-bit
    FLOAT, **additive/non-breaking**), the `decode_timestamp` extraction into `adapters/datetime_field.py`
    with `bp_parser` re-export (**behavior-preserving/non-breaking**), `TemperatureMeasurementParser`,
    `HealthThermometerBleAdapter`/`MockThermometerAdapter`, `VOF_TEMP_*`, the `temp` / `mock-temp` short
    names, the new protocol doc, and the `brief-validation-modes.md`/`brief-config-file.md` docs.
    Reference the FR-TEMP-*/NFR-TEMP-* IDs. If any EviTrace-ported test pattern is used, record it in
    `NOTICE`.
  - _Design: §Docs deliverables. Requirements: NFR-TEMP-1, NFR-TEMP-2, NFR-TEMP-3, NFR-TEMP-4, NFR-TEMP-5, NFR-TEMP-6_

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP path; core
  implementation sub-tasks are never marked optional.
- Each task references the FR-TEMP-*/NFR-TEMP-* requirements it satisfies and the design section(s)
  that specify it, for traceability toward the planned preprint.
- Order is behavior-preserving-first: the additive `decode_float` (task 1) and the behavior-preserving
  `decode_timestamp` extraction (task 2) land under the existing suite as a guardrail before any new
  temperature-specific code depends on them.
- Property tests implement the five design Correctness Properties, one Hypothesis test each, ≥100
  iterations, tagged with the design property (design §Testing Strategy).
- The two briefs (task 9) build no code and change no behavior; they are idea-only records.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "2", "3", "5"] },
    { "id": 1, "tasks": ["1.1", "3.1", "4", "6"] },
    { "id": 2, "tasks": ["4.1", "4.2", "4.3", "4.4", "6.1", "7"] },
    { "id": 3, "tasks": ["7.1", "8"] },
    { "id": 4, "tasks": ["8.1", "8.2", "9"] },
    { "id": 5, "tasks": ["10"] }
  ]
}
```
