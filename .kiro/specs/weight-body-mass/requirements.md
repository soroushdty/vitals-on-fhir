# Requirements Document

**Spec: weight-body-mass** (weight scale — fourth and final phase-2 slice)

## Introduction

This spec is the fourth and last sibling in roadmap phase 2 (home health devices), following
`home-health-devices` (blood pressure), `oxygen-saturation` (pulse oximetry), and `body-temperature`
(health thermometer). It adds acquisition of body weight from a standard Bluetooth **Weight Scale**
device (the WSS profile) and represents each reading as an HL7 FHIR R4 Observation conforming to the
US Core Body Weight profile.

Phase 2 is delivered as a series of sibling specs, one per profile, to keep each reviewable and
landable on its own (see `docs/adr-0001-open-phase-2-home-health-devices.md`). **This spec covers
body weight only** and completes the phase-2 vital-sign set the ADR anticipated ("new `ScalarVital`
types (... body weight)").

Like oxygen saturation and body temperature — and unlike blood pressure, which introduced the first
`ComponentVital` — body weight is a single scalar quantity. It therefore lands as a new
**`ScalarVital`** subclass (`BodyWeight`). Because the earlier slices already extracted the reusable
`BleConnection` lifecycle and the shared `decode_timestamp` helper, and because the `ScalarVitalMapper`
already builds an Observation from a scalar vital's class metadata, **this slice needs no new FHIR
mapper code and no new BLE lifecycle** — it reuses both, exactly as the SpO2 and temperature slices
did. That narrows this spec's new surface to: a new `ScalarVital`, a new Weight Measurement payload
parser with a new **unit-scaled uint16** decode, a new adapter composing the existing lifecycle,
config, a mock source, wiring, and docs.

### Why this profile differs from the earlier slices

The Weight Scale Service (WSS) profile differs from the earlier phase-2 profiles in three ways, all of
which this spec addresses or explicitly bounds:

1. **Unit-dependent uint16 scaling — a new decode primitive.** The Weight Measurement value is a plain
   **uint16**, not an IEEE-11073 SFLOAT or FLOAT. Its physical meaning depends on the flags byte:
   in SI mode the raw value is scaled by **0.005 kg** per unit; in Imperial mode it is scaled by
   **0.01 lb** per unit. The two multipliers are **not** related by a simple after-the-fact unit
   conversion — the resolution itself differs — so decoding SI bytes with the Imperial multiplier (or
   vice versa) yields a value wrong by roughly a factor of two, which is close enough to look
   plausible and therefore dangerous. This slice adds a dedicated unit-scaled uint16 decode; it does
   **not** touch the shared `adapters/sfloat.py` SFLOAT/FLOAT decoders, which weight does not use.
   *(Protocol facts rephrased for licensing compliance; sources cited in `docs/`.)*
2. **Normalization to kilograms.** US Core Body Weight is expressed in kilograms (UCUM `kg`), so an
   Imperial (pounds) reading is normalized to kilograms before the Reading is constructed — analogous
   to the temperature Fahrenheit→Celsius and the blood-pressure kPa→mmHg normalizations, but the
   normalization is folded into the unit-dependent scaling step rather than applied afterward.
3. **Additional optional fields.** The Weight Measurement flags byte can declare an optional
   measurement timestamp (bit 1), an optional user ID (bit 2, 1 byte), and an optional BMI-and-height
   pair (bit 3, two uint16 fields). This slice targets the **weight value only**. The user ID, BMI,
   and height fields are **length-accounted only** (so a short payload is rejected) and are **not
   modelled** in the Reading — mirroring how the temperature slice length-accounted but did not model
   the temperature-type field. See Out of scope.

### Relationship to the earlier slices

- **Reuses** the `BleConnection` lifecycle (unchanged), the `ScalarVitalMapper` (unchanged — resolved
  via the existing MRO registry, no new mapper code), the `DuplicateValidator` (unchanged — its scalar
  identity key already covers body weight), and the `SensorContactValidator` (unchanged — it passes
  non-heart-rate vitals through).
- **Reuses** the per-vital-class `PlausibleRangeValidator` generalization: it already supports
  per-class `(min, max)` overrides, so body weight is wired by adding a `BodyWeight` entry to the
  overrides map — no further validator change.
- **Reuses** the shared `adapters/datetime_field.decode_timestamp` (and `TIMESTAMP_SIZE`) for the
  optional measurement timestamp — the same helper the blood-pressure and temperature parsers use — so
  no new date-time decode is introduced.

### Design note carried forward — device timestamp timezone

The blood-pressure slice interprets a device's zoneless timestamp as host local time and returns it
timezone-aware (documented in `docs/protocol-blood-pressure-measurement.md` and
`docs/brief-config-file.md`), and the temperature slice reused that convention. The WSS Weight
Measurement characteristic **may carry an optional timestamp** (flags bit 1). Where present, this slice
SHALL reuse the same convention (interpret the zoneless timestamp as host local time, return it
timezone-aware) via the shared helper; where absent, the Reading's `effective` time is the processing
time (`now()`), timezone-aware. This spec therefore introduces no new timezone behavior.

### Numbering

The decision to open phase 2 is recorded in `docs/adr-0001-open-phase-2-home-health-devices.md`.
New functional (**FR-WT-\***) and non-functional (**NFR-WT-\***) requirement IDs are additive and
distinct from the blood-pressure slice's `FR-HH-*`/`NFR-HH-*`, the SpO2 slice's
`FR-SPO2-*`/`NFR-SPO2-*`, and the temperature slice's `FR-TEMP-*`/`NFR-TEMP-*` IDs, so each sibling
spec's traceability stays unambiguous for the planned preprint. Existing MVP, blood-pressure, SpO2,
and temperature IDs are preserved and not renumbered. Acceptance criteria follow EARS patterns and
INCOSE quality rules, mirroring the style of the sibling specs.

## Glossary

- **Pipeline**: the end-to-end vitals-on-fhir system (adapter → validators → mapper → sinks).
- **WSS_Profile**: the standard Bluetooth SIG Weight Scale Service (GATT service UUID `0x181D`).
- **Weight_Characteristic**: the WSS Weight Measurement characteristic (GATT `0x2A9D`), delivered via
  GATT indications.
- **Weight_Adapter**: the concrete `DeviceAdapter` acquiring readings over the WSS_Profile.
- **Weight_Parser**: the `GattCharacteristicParser` subclass decoding a Weight_Characteristic payload
  into a `BodyWeight` domain object.
- **Unit_Scaler**: the pure-function unit-dependent uint16 decode that converts a raw Weight
  Measurement value to kilograms, choosing the SI (0.005 kg) or Imperial (0.01 lb, then →kg) scaling
  from the flags byte. New to this slice; distinct from SFLOAT/FLOAT.
- **BodyWeight**: the new `ScalarVital` subclass carrying a single weight value in kilograms.
- **Scalar_Mapper**: the existing `ScalarVitalMapper`, reused unchanged by this spec.
- **Validator_Chain**: the `ValidatorChain` running validators in registration order.
- **Reading**: a single decoded, well-formed `BodyWeight` measurement.
- **Observation**: a `fhir.resources` R4 `Observation` model instance.
- **Effective_Time**: the timezone-aware time a measurement was taken (`effective` field).
- **Issued_Time**: the timezone-aware time a measurement was processed (`issued` field).
- **CLI**: `cli.py`, the composition root — the only module that instantiates concrete classes.

---

## Requirements

### Functional requirements

#### FR-WT-1 — Body-weight vital-sign type
*Traces to product FR-13 (extensibility), the object-model `ScalarVital` contract, and ADR-0001.*

- THE Pipeline SHALL define `BodyWeight` as a frozen `ScalarVital` subclass under `vitals/builtin/`,
  carrying the weight in kilograms as its single numeric `value`.
- THE `BodyWeight` type SHALL declare its `loinc_code` (`29463-7`, body weight), its `us_core_profile`
  (the US Core Body Weight profile), its `ucum_unit` (`kg`), and a default `plausible_range`.
- WHERE `BodyWeight` omits required class metadata, THE Pipeline SHALL raise at import time, consistent
  with the existing `VitalSign`/`ScalarVital` metadata-enforcement contract.
- THE `BodyWeight` type SHALL be exported from `vitals/__init__.py` under `# Concrete defaults`.
- Introducing `BodyWeight` SHALL NOT change any existing public ABC method signature or exported name.

#### FR-WT-2 — Unit-dependent uint16 weight decoding
*Traces to product FR-3 (parsing), NFR-6 (maintainability), and ADR-0001.*

- THE Weight_Parser SHALL decode the mandatory weight field as a little-endian **uint16** and scale it
  to kilograms using the resolution selected by the flags byte: WHERE the flags byte indicates SI
  units (bit 0 clear), THE Weight_Parser SHALL multiply the raw value by the SI resolution (`0.005`
  kg); WHERE the flags byte indicates Imperial units (bit 0 set), THE Weight_Parser SHALL multiply the
  raw value by the Imperial resolution (`0.01` lb) and normalize the result to kilograms.
- THE Unit_Scaler SHALL be a pure function so the SI-versus-Imperial resolution choice and the
  pounds→kilograms normalization are exercised without hardware, consistent with the existing
  heart-rate, blood-pressure, pulse-oximeter, and temperature parsers, which delegate byte-level logic
  to pure functions.
- THE Unit_Scaler SHALL NOT reuse the IEEE-11073 SFLOAT or FLOAT decoders, because the Weight
  Measurement value is a plain scaled uint16, not a medical float; adding it SHALL leave
  `adapters/sfloat.py` unchanged.
- THE resulting `BodyWeight.value` SHALL always be in kilograms regardless of the device's reporting
  unit, so the `kg` UCUM code and the `VOF_WEIGHT_*` bounds are always applied against a consistent
  unit.

#### FR-WT-3 — Weight Measurement payload parsing
*Traces to product FR-3 (parsing) and ADR-0001.*

- WHEN the Weight_Parser receives a Weight_Characteristic payload, THE Weight_Parser SHALL decode the
  flags byte and the mandatory uint16 weight field per the Bluetooth SIG Weight Measurement
  specification, using the scaled value (in kilograms) to construct the Reading.
- WHERE the flags byte indicates a timestamp is present (bit 1 set), THE Weight_Parser SHALL decode the
  org.bluetooth date-time field via the shared `decode_timestamp` helper and use it as the Reading's
  Effective_Time, interpreting the zoneless timestamp as host local time and returning it
  timezone-aware, consistent with the blood-pressure and temperature convention; WHERE no timestamp is
  present, THE Weight_Parser SHALL set the Effective_Time to the current time (timezone-aware). The
  clock SHALL be injectable for tests.
- WHERE the flags byte indicates a user ID is present (bit 2 set) and/or a BMI-and-height pair is
  present (bit 3 set), THE Weight_Parser SHALL account for those fields when computing the minimum
  payload length, even though they are not modelled in the Reading.
- IF a payload is too short for the fields its flags byte declares, or a declared timestamp is not a
  valid calendar date-time, THEN THE Weight_Parser SHALL return `None` and THE Weight_Adapter SHALL
  drop it without yielding a Reading.
- THE Weight_Parser byte-level decoding SHALL be implemented as pure functions the parser class
  delegates to, consistent with the existing parsers, and SHALL use the Unit_Scaler for the weight
  value and the shared `decode_timestamp` for the optional timestamp.
- THE `docs/` directory SHALL cite the Bluetooth SIG Weight Scale Service / Weight Measurement
  specification (name, version, and URL or publication date) used to implement the parser.

#### FR-WT-4 — BLE acquisition via the shared lifecycle
*Traces to product FR-1, FR-2, FR-13, and ADR-0001.*

- THE Weight_Adapter SHALL acquire readings over the WSS_Profile by composing the existing reusable
  BLE lifecycle (`BleConnection`), configured with the WSS_Profile service UUID (`0x181D`) and the
  Weight_Characteristic UUID (`0x2A9D`), delegating payload decoding to the Weight_Parser.
- THE Weight_Adapter SHALL reuse the shared lifecycle **by composition without modifying it**, keeping
  every concrete adapter within the object-model 3-level inheritance cap.
- THE Weight_Adapter and the shared lifecycle SHALL import `bleak` lazily inside the methods that use
  it, never at module level, consistent with the existing BLE rule.
- WHEN an indication is received on the subscribed characteristic, THE Weight_Adapter SHALL pass the
  payload to the Weight_Parser and yield the resulting Reading from its `vitals()` async generator
  without user intervention. (As documented in the temperature slice, `bleak`'s `start_notify`
  transparently enables indications or notifications as the characteristic declares, so `BleConnection`
  needs no change for the indication-delivered Weight Measurement characteristic.)
- THE Pipeline SHALL continue to support exactly one connected device at a time (unchanged from MVP).

#### FR-WT-5 — FHIR mapping via the existing scalar mapper
*Traces to product FR-4, FR-8, NFR-4, and ADR-0001.*

- WHEN a `BodyWeight` Reading is accepted, THE Pipeline SHALL convert it to a FHIR R4 `Observation`
  conforming to the US Core Body Weight profile, reusing the existing Scalar_Mapper with **no new
  mapper code**.
- THE resulting Observation SHALL carry `status` `final`, the vital-signs `category`, the panel `code`
  from the vital's `loinc_code` (`29463-7`), and a `valueQuantity` whose UCUM `code` is `kg` and whose
  value is the weight in kilograms.
- THE Observation SHALL be constructed using `fhir.resources` model classes so model validation runs
  at construction time; IF construction fails validation, THEN THE Pipeline SHALL log at `ERROR`
  (without the measurement value) and SHALL NOT serve or store the Observation.
- THE mapper registry SHALL resolve `BodyWeight` to the Scalar_Mapper by MRO walk, leaving
  `HeartRate → ScalarVitalMapper`, `OxygenSaturation → ScalarVitalMapper`,
  `BodyTemperature → ScalarVitalMapper`, and `BloodPressure → ComponentVitalMapper` resolution
  unchanged.

#### FR-WT-6 — Per-vital-class plausibility validation
*Traces to product FR-3 (validation) and ADR-0001.*

- THE Pipeline SHALL validate a `BodyWeight` Reading by checking its value (in kilograms) against a
  plausible weight range, rejecting the Reading if the value is out of range.
- THE Pipeline SHALL source the weight plausible bounds from configuration using the `VOF_WEIGHT_*`
  naming convention (`VOF_WEIGHT_MIN`, `VOF_WEIGHT_MAX`), falling back to the `BodyWeight` class
  `plausible_range` when unset.
- THE plausible-range validation SHALL apply the correct bounds per vital-sign class using the
  existing per-vital-class overrides map: weight bounds (`VOF_WEIGHT_*`) SHALL apply only to
  body-weight Readings, with no cross-application of one vital's bounds to another. The
  `PlausibleRangeValidator` ABC and construction surface SHALL NOT change beyond adding the new entry
  to the overrides map in the composition root.
- WHEN the Validator_Chain rejects a Reading, THE Pipeline SHALL log the rejection at `INFO` without
  the measurement value and SHALL NOT produce an Observation, unchanged from existing behavior.
- Duplicate detection for `BodyWeight` SHALL reuse the existing scalar identity key
  (`device_id`, `effective`, `value`) with no change to the `DuplicateValidator`.

#### FR-WT-7 — API and CapabilityStatement coverage
*Traces to product FR-11 and ADR-0001.*

- THE API `GET /fhir/metadata` CapabilityStatement SHALL reflect that body-weight Observations are
  searchable through the existing read-only endpoints.
- THE API `GET /fhir/Observation` search SHALL filter body-weight Observations by their LOINC `code`
  using the existing `code` search parameter, with no new endpoint added.
- THE API SHALL continue to expose no write operation.

#### FR-WT-8 — Adapter selection for the weight scale
*Traces to product FR-13 and ADR-0001.*

- THE CLI adapter resolver SHALL map new short names for the Weight_Adapter and its mock counterpart
  alongside the existing `mock`, `miband10`, `bp`, `mock-bp`, `spo2`, `mock-spo2`, `temp`, and
  `mock-temp` names.
- THE CLI SHALL continue to allow selecting any `DeviceAdapter` by fully qualified
  `package.module.ClassName`, so third-party weight-scale adapters need no repository change.
- THE Pipeline SHALL provide a mock weight source so the weight path (including out-of-range and
  Imperial-normalization readings) can be exercised without hardware; the mock source SHALL NOT import
  `bleak`.

#### FR-WT-9 — Configuration surface checkpoint (final phase-2 checkpoint)
*Traces to product NFR-6, `docs/brief-config-file.md`, and ADR-0001.*

- WHEN this slice adds `VOF_WEIGHT_*`, THE spec deliverables SHALL update the configuration-surface
  checkpoint in `docs/brief-config-file.md`: re-count the total `VOF_*` variables after `VOF_WEIGHT_*`
  lands and record an explicit judgment of whether the flat env-var list has become "awkward" enough
  to warrant promoting the optional `config.yaml` idea to its own spec. As body weight is the final
  phase-2 vital, this checkpoint SHALL state the completed phase-2 range-key surface and give the
  phase-closing recommendation.
- THE checkpoint update SHALL NOT itself build a config-file layer; it SHALL only record the count and
  the judgment, consistent with the brief's guardrails.

### Non-functional requirements

#### NFR-WT-1 — No breaking changes to the object model
*Traces to product NFR-6, the object-model conventions, and ADR-0001.*

- THE new vital-sign, parser, adapter, decode-function, and validator-wiring changes SHALL be
  introduced by subclassing, composing, or additively extending the existing ABCs and modules, with no
  change to any existing ABC method signature or `__all__` public name.
- Adding the Unit_Scaler SHALL introduce only new members in the new `adapters/weight_parser.py`
  module; it SHALL NOT alter `adapters/sfloat.py`, the existing `decode_sfloat`/`decode_float`
  functions, the shared `decode_timestamp` helper, or the `Validator` ABC.
- Any change that would alter an existing public ABC or exported name SHALL be treated as breaking and
  recorded in `CHANGELOG.md` with a `**Breaking:**` note; the intent of this spec is to avoid such
  changes.

#### NFR-WT-2 — Dependency directions preserved
*Traces to product NFR-6 and the structure steering doc.*

- After this spec is implemented, `uv run pytest tests/test_dependency_directions.py` SHALL pass,
  confirming no forbidden cross-package imports were introduced.
- THE `vitals` package (including `BodyWeight`) SHALL continue to import no other `vitals_on_fhir`
  package. THE Weight_Parser and Unit_Scaler SHALL live in `adapters` and add no cross-package import.

#### NFR-WT-3 — Interoperability
*Traces to product NFR-4.*

- THE Pipeline SHALL produce body-weight Observations conforming to FHIR R4 (4.0.1) and the US Core
  Body Weight profile, using LOINC and UCUM codings.
- THE Pipeline SHALL validate every generated resource with `fhir.resources` model validation before
  serving or storing it.
- THE domain model SHALL retain the LOINC and UCUM bindings as class metadata independent of FHIR, so
  a future non-FHIR target mapper can consume `BodyWeight` objects without changes to the `vitals`
  package.

#### NFR-WT-4 — Provenance and licensing
*Traces to the security/provenance steering doc and product license rules.*

- Every source file added by this spec SHALL begin with `# SPDX-License-Identifier: AGPL-3.0-or-later`.
- Protocol knowledge for the WSS_Profile and the unit-dependent uint16 weight encoding SHALL be sourced
  only from published Bluetooth SIG, HL7/FHIR, or public vendor specifications, and cited in `docs/`;
  no code SHALL be copied, translated, or closely paraphrased from other projects or vendor SDKs.
- WHERE any third-party or EviTrace-ported material is included, THE Pipeline SHALL record it in
  `NOTICE` with the required fields.

#### NFR-WT-5 — Security and privacy unchanged
*Traces to product NFR-5 and the security steering doc.*

- THE new type, parser, adapter, decode-function, and validator-wiring changes SHALL NOT introduce any
  non-FHIR side channel for measurement data.
- THE Pipeline SHALL NOT include measurement values in log messages at `INFO` level or above, and SHALL
  NOT include `VOF_API_TOKEN` in any log message at any level.
- THE optional user ID field in the Weight Measurement payload SHALL NOT be decoded, stored, logged, or
  otherwise retained; it is length-accounted only, so no per-user identifier enters the Pipeline.
- THE CLI SHALL continue to bind to `127.0.0.1` by default; this spec SHALL NOT introduce remote
  deployment.

#### NFR-WT-6 — Test coverage
*Traces to product NFR-6 and the testing steering doc.*

- THE test suite SHALL include: an `__init_subclass__` metadata test for `BodyWeight`; Unit_Scaler
  tests covering SI and Imperial scaling and the pounds→kilograms normalization (including a known SI
  pair and a known Imperial pair, and a guard that the two multipliers are not interchanged);
  Weight_Parser tests covering well-formed SI and Imperial payloads, the optional timestamp field, the
  optional user-ID and BMI-and-height field length accounting, and malformed/short/invalid-timestamp
  payloads; a mapper test asserting a valid US Core Body Weight Observation (weight value, `kg` UCUM
  code, LOINC `29463-7`); validator tests confirming weight bounds apply to body weight and do not
  cross-apply to other vitals; and Weight_Adapter/`BleConnection` behavior tests. The fast suite SHALL
  pass without hardware.
- THE existing heart-rate, blood-pressure, oxygen-saturation, and body-temperature test suites
  (including the dependency-direction test) SHALL remain green, serving as the regression guardrail —
  in particular confirming `adapters/sfloat.py` and the shared `decode_timestamp` helper are untouched.
- Hardware-dependent tests for a real weight scale SHALL carry the `hardware` marker and be excluded
  from CI, consistent with the MVP convention.

---

## Out of scope

Per the product steering document and ADR-0001, this spec excludes:

- Modelling the optional **user ID** field as structured Observation data or as any per-user routing.
  It is length-accounted only and never decoded, stored, or logged (see NFR-WT-5). Multi-user support
  is not in phase-2 scope.
- Modelling the optional **BMI and height** fields. They are length-accounted only; deriving or
  emitting a separate BMI or Body-Height Observation (e.g. LOINC `39156-5` BMI, `8302-2` body height)
  may be added later, additively, without changing this spec's output. These optional fields are also
  uncommon on standalone standard-WSS scales, so they are exercised only by synthetic parser payloads
  (via `required_length`), not expected from real target hardware.
- The Body Composition Service (`0x181B`) and its Body Composition Measurement (`0x2A9C`) — a distinct
  profile for impedance-derived metrics (body-fat %, muscle mass, BMR, etc.). Not in scope. On real
  consumer scales these metrics have **no standard BLE channel**: they are bioimpedance-derived and
  delivered over proprietary BLE frames or a vendor cloud API, which `product.md` and
  `security-privacy.md` put permanently out of scope (no proprietary/reverse-engineered protocols). The
  intended home for body composition is the **phase-3 phone-aggregator** path, where Android Health
  Connect exposes typed records (`BodyFatRecord`, `BasalMetabolicRateRecord`, `LeanBodyMassRecord`) via
  a documented API — see the phase-3 preview note in `docs/roadmap.md`. Not built here.
- Multiple simultaneous connected devices (still one device at a time).
- Persistence beyond in-memory storage (no database, disk, or remote store) — phase 4.
- Remote or cloud deployment and exposure to untrusted networks.
- SMART on FHIR authentication and outbound FHIR sinks — phase 4; not stubbed or referenced here.
- Phone health aggregators (Health Connect, HealthKit) — phase 3.
- Proprietary or reverse-engineered device protocols and any circumvention of device security.
- Writing to external EHRs or FHIR servers, and any write operation on the local API.
- Building the `docs/brief-config-file.md` `config.yaml` layer; this spec adds `VOF_WEIGHT_*` as flat
  env vars and updates the surface-size checkpoint in that brief (the final phase-2 checkpoint), but
  does not build a config-file layer.
