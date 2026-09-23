# Requirements Document

**Spec: body-temperature** (health thermometer — third phase-2 slice)

## Introduction

This spec is the third sibling in roadmap phase 2 (home health devices), following
`home-health-devices` (blood pressure) and `oxygen-saturation` (pulse oximetry). It adds acquisition
of body temperature from a standard Bluetooth **Health Thermometer** device (the HTS profile) and
represents each reading as an HL7 FHIR R4 Observation conforming to the US Core Body Temperature
profile.

Phase 2 is delivered as a series of sibling specs, one per profile, to keep each reviewable and
landable on its own (see `docs/adr-0001-open-phase-2-home-health-devices.md`). **This spec covers
body temperature only.** Body weight remains deferred to its own sibling spec.

Like oxygen saturation — and unlike blood pressure, which introduced the first `ComponentVital` —
body temperature is a single scalar quantity. It therefore lands as a new **`ScalarVital`** subclass,
exactly as ADR-0001 anticipated ("new `ScalarVital` types (... body temperature ...)"). Because the
blood-pressure slice already extracted the reusable `BleConnection` lifecycle and the
`ScalarVitalMapper` already builds an Observation from a scalar vital's class metadata, **this slice
needs no new FHIR mapper code and no new BLE lifecycle** — it reuses both, mirroring the SpO2 slice.
That narrows this spec's new surface to: a new `ScalarVital`, a new Temperature Measurement payload
parser, a new IEEE-11073 **32-bit FLOAT** decoder alongside the existing 16-bit SFLOAT decoder, a new
adapter composing the existing lifecycle, config, a mock source, wiring, and docs.

### Why this profile differs from the earlier slices

The Health Thermometer Service (HTS) profile differs from both the Heart Rate Service and the earlier
phase-2 profiles in three ways, all of which this spec addresses or explicitly bounds:

1. **32-bit FLOAT value encoding.** The Temperature Measurement value is an IEEE-11073 **32-bit
   FLOAT** (an 8-bit signed exponent and a 24-bit signed mantissa) — related to, but **distinct
   from**, the IEEE-11073 16-bit SFLOAT (4-bit exponent, 12-bit mantissa) that blood pressure and
   SpO2 use. The two share the shared decoder module but are separate functions with their own
   reserved special values. This spec adds a `decode_float` (FLOAT) function alongside the existing
   `decode_sfloat` in the shared `adapters/sfloat.py` module.
2. **Unit selection with normalization.** The Temperature Measurement flags byte selects Celsius or
   Fahrenheit (bit 0). US Core Body Temperature is expressed in degrees Celsius (UCUM `Cel`), so a
   Fahrenheit reading is normalized to Celsius before the Reading is constructed — analogous to the
   blood-pressure kPa→mmHg normalization.
3. **Two measurement characteristics.** HTS defines a mandatory **Temperature Measurement**
   characteristic (`0x2A1C`, delivered via GATT *indications*) and an optional **Intermediate
   Temperature** characteristic (`0x2A1E`, delivered via *notifications*). This slice targets the
   **Temperature Measurement** characteristic only. The Intermediate Temperature characteristic is
   **deferred** (see Out of scope), mirroring how the SpO2 slice deferred the PLX spot-check
   characteristic — so this slice needs no change to the shared lifecycle.

### Relationship to the earlier slices

- **Reuses** the `BleConnection` lifecycle (unchanged), the `ScalarVitalMapper` (unchanged — resolved
  via the existing MRO registry, no new mapper code), the `DuplicateValidator` (unchanged — its scalar
  identity key already covers body temperature), and the `SensorContactValidator` (unchanged — it
  passes non-heart-rate vitals through).
- **Reuses** the per-vital-class `PlausibleRangeValidator` generalization introduced by the SpO2
  slice: it already supports per-class `(min, max)` overrides, so body temperature is wired by adding
  a `BodyTemperature` entry to the overrides map — no further validator change.
- **Extends** the shared `adapters/sfloat.py` decoder module with a `decode_float` (IEEE-11073 32-bit
  FLOAT) function, additive to the existing `decode_sfloat`, so the FLOAT encoding exists once and is
  available to any future 32-bit-FLOAT parser.

### Design note carried forward — device timestamp timezone

The blood-pressure slice interprets a device's zoneless timestamp as host local time and returns it
timezone-aware (documented in `docs/protocol-blood-pressure-measurement.md` and
`docs/brief-config-file.md`). The HTS Temperature Measurement characteristic **may carry an optional
timestamp** (flags bit 1). Where present, this slice SHALL reuse the blood-pressure convention
(interpret the zoneless timestamp as host local time, return it timezone-aware) rather than defining a
new one; where absent, the Reading's `effective` time is the processing time (`now()`),
timezone-aware. This spec therefore introduces no new timezone behavior.

### Numbering

The decision to open phase 2 is recorded in `docs/adr-0001-open-phase-2-home-health-devices.md`.
New functional (**FR-TEMP-\***) and non-functional (**NFR-TEMP-\***) requirement IDs are additive and
distinct from the blood-pressure slice's `FR-HH-*`/`NFR-HH-*` and the SpO2 slice's
`FR-SPO2-*`/`NFR-SPO2-*` IDs, so each sibling spec's traceability stays unambiguous for the planned
preprint. Existing MVP, blood-pressure, and SpO2 IDs are preserved and not renumbered. Acceptance
criteria follow EARS patterns and INCOSE quality rules, mirroring the style of the sibling specs.

## Glossary

- **Pipeline**: the end-to-end vitals-on-fhir system (adapter → validators → mapper → sinks).
- **HTS_Profile**: the standard Bluetooth SIG Health Thermometer Service (GATT service UUID `0x1809`).
- **Temperature_Characteristic**: the HTS Temperature Measurement characteristic (GATT `0x2A1C`),
  delivered via GATT indications.
- **Intermediate_Temperature_Characteristic**: the HTS Intermediate Temperature characteristic (GATT
  `0x2A1E`), delivered via notifications; out of scope for this slice.
- **Temp_Adapter**: the concrete `DeviceAdapter` acquiring readings over the HTS_Profile.
- **Temp_Parser**: the `GattCharacteristicParser` subclass decoding a Temperature_Characteristic
  payload into a `BodyTemperature` domain object.
- **FLOAT**: the IEEE-11073 **32-bit** float encoding (8-bit signed exponent, 24-bit signed mantissa)
  used for the temperature value, with reserved special values (NaN, NRes, ±INFINITY, reserved) that
  are not usable. Distinct from SFLOAT.
- **SFLOAT**: the IEEE-11073 **16-bit** short-float encoding (4-bit signed exponent, 12-bit signed
  mantissa) used by the blood-pressure and pulse-oximeter parsers.
- **Float_Decoder**: the shared pure-function IEEE-11073 32-bit FLOAT decoding added to
  `adapters/sfloat.py` alongside the existing SFLOAT decoder.
- **BodyTemperature**: the new `ScalarVital` subclass carrying a single temperature value in Celsius.
- **Scalar_Mapper**: the existing `ScalarVitalMapper`, reused unchanged by this spec.
- **Validator_Chain**: the `ValidatorChain` running validators in registration order.
- **Reading**: a single decoded, well-formed `BodyTemperature` measurement.
- **Observation**: a `fhir.resources` R4 `Observation` model instance.
- **Effective_Time**: the timezone-aware time a measurement was taken (`effective` field).
- **Issued_Time**: the timezone-aware time a measurement was processed (`issued` field).
- **CLI**: `cli.py`, the composition root — the only module that instantiates concrete classes.

---

## Requirements

### Functional requirements

#### FR-TEMP-1 — Body-temperature vital-sign type
*Traces to product FR-13 (extensibility), the object-model `ScalarVital` contract, and ADR-0001.*

- THE Pipeline SHALL define `BodyTemperature` as a frozen `ScalarVital` subclass under
  `vitals/builtin/`, carrying the temperature in degrees Celsius as its single numeric `value`.
- THE `BodyTemperature` type SHALL declare its `loinc_code` (`8310-5`, body temperature), its
  `us_core_profile` (the US Core Body Temperature profile), its `ucum_unit` (`Cel`), and a default
  `plausible_range`.
- WHERE `BodyTemperature` omits required class metadata, THE Pipeline SHALL raise at import time,
  consistent with the existing `VitalSign`/`ScalarVital` metadata-enforcement contract.
- THE `BodyTemperature` type SHALL be exported from `vitals/__init__.py` under `# Concrete defaults`.
- Introducing `BodyTemperature` SHALL NOT change any existing public ABC method signature or exported
  name.

#### FR-TEMP-2 — Shared IEEE-11073 32-bit FLOAT decoding
*Traces to product FR-3 (parsing), NFR-6 (maintainability), and ADR-0001.*

- THE Pipeline SHALL provide IEEE-11073 **32-bit FLOAT** decoding as a pure function (`Float_Decoder`)
  in the shared `adapters/sfloat.py` module, alongside the existing 16-bit SFLOAT decoder, so a
  Temperature_Characteristic value can be decoded without duplicating the encoding.
- THE Float_Decoder SHALL decode a 32-bit FLOAT as an 8-bit signed exponent and a 24-bit signed
  mantissa, distinct from the 16-bit SFLOAT's 4-bit exponent and 12-bit mantissa.
- THE Float_Decoder SHALL treat the FLOAT reserved mantissa values (NaN, NRes, +INFINITY, −INFINITY,
  and the reserved value) as not representing a usable number, returning a sentinel the caller drops
  on, using the FLOAT-specific reserved values rather than the SFLOAT ones.
- THE Float_Decoder SHALL reside in the `adapters` package and SHALL depend only on the Python
  standard library, introducing no new cross-package dependency.
- Adding the Float_Decoder SHALL be additive: the existing `decode_sfloat` function and its behavior
  SHALL be unchanged, and the full existing test suite SHALL remain green.

#### FR-TEMP-3 — Temperature Measurement payload parsing
*Traces to product FR-3 (parsing) and ADR-0001.*

- WHEN the Temp_Parser receives a Temperature_Characteristic payload, THE Temp_Parser SHALL decode the
  flags byte and the 32-bit FLOAT temperature field per the Bluetooth SIG Temperature Measurement
  specification, using the temperature value to construct the Reading.
- WHERE the flags byte indicates the measurement unit is Fahrenheit (bit 0 set), THE Temp_Parser SHALL
  normalize the value to degrees Celsius before constructing the Reading; WHERE the flags byte
  indicates Celsius (bit 0 clear), THE Temp_Parser SHALL use the value unchanged.
- WHERE the flags byte indicates a timestamp is present (bit 1 set), THE Temp_Parser SHALL decode the
  org.bluetooth date-time field and use it as the Reading's Effective_Time, interpreting the zoneless
  timestamp as host local time and returning it timezone-aware, consistent with the blood-pressure
  convention; WHERE no timestamp is present, THE Temp_Parser SHALL set the Effective_Time to the
  current time (timezone-aware). The clock SHALL be injectable for tests.
- WHERE the flags byte indicates a temperature type is present (bit 2 set), THE Temp_Parser SHALL
  account for the temperature-type field when computing the minimum payload length, even though the
  field is not modelled in the Reading.
- IF a payload is too short for the fields its flags byte declares, or the temperature FLOAT is a
  reserved/unusable value, or a declared timestamp is not a valid calendar date-time, THEN THE
  Temp_Parser SHALL return `None` and THE Temp_Adapter SHALL drop it without yielding a Reading.
- THE Temp_Parser byte-level decoding SHALL be implemented as pure functions the parser class
  delegates to, consistent with the existing heart-rate, blood-pressure, and pulse-oximeter parsers,
  and SHALL use the shared Float_Decoder.
- THE `docs/` directory SHALL cite the Bluetooth SIG Health Thermometer Service / Temperature
  Measurement specification (name, version, and URL or publication date) used to implement the parser.

#### FR-TEMP-4 — BLE acquisition via the shared lifecycle
*Traces to product FR-1, FR-2, FR-13, and ADR-0001.*

- THE Temp_Adapter SHALL acquire readings over the HTS_Profile by composing the existing reusable BLE
  lifecycle (`BleConnection`), configured with the HTS_Profile service UUID (`0x1809`) and the
  Temperature_Characteristic UUID (`0x2A1C`), delegating payload decoding to the Temp_Parser.
- THE Temp_Adapter SHALL reuse the shared lifecycle **by composition without modifying it**, keeping
  every concrete adapter within the object-model 3-level inheritance cap.
- THE Temp_Adapter and the shared lifecycle SHALL import `bleak` lazily inside the methods that use
  it, never at module level, consistent with the existing BLE rule.
- WHEN an indication is received on the subscribed characteristic, THE Temp_Adapter SHALL pass the
  payload to the Temp_Parser and yield the resulting Reading from its `vitals()` async generator
  without user intervention.
- THE Pipeline SHALL continue to support exactly one connected device at a time (unchanged from MVP).

#### FR-TEMP-5 — FHIR mapping via the existing scalar mapper
*Traces to product FR-4, FR-8, NFR-4, and ADR-0001.*

- WHEN a `BodyTemperature` Reading is accepted, THE Pipeline SHALL convert it to a FHIR R4
  `Observation` conforming to the US Core Body Temperature profile, reusing the existing Scalar_Mapper
  with **no new mapper code**.
- THE resulting Observation SHALL carry `status` `final`, the vital-signs `category`, the panel `code`
  from the vital's `loinc_code` (`8310-5`), and a `valueQuantity` whose UCUM `code` is `Cel` and whose
  value is the temperature in degrees Celsius.
- THE Observation SHALL be constructed using `fhir.resources` model classes so model validation runs
  at construction time; IF construction fails validation, THEN THE Pipeline SHALL log at `ERROR`
  (without the measurement value) and SHALL NOT serve or store the Observation.
- THE mapper registry SHALL resolve `BodyTemperature` to the Scalar_Mapper by MRO walk, leaving
  `HeartRate → ScalarVitalMapper`, `OxygenSaturation → ScalarVitalMapper`, and
  `BloodPressure → ComponentVitalMapper` resolution unchanged.

#### FR-TEMP-6 — Per-vital-class plausibility validation
*Traces to product FR-3 (validation) and ADR-0001.*

- THE Pipeline SHALL validate a `BodyTemperature` Reading by checking its value (in Celsius) against a
  plausible temperature range, rejecting the Reading if the value is out of range.
- THE Pipeline SHALL source the temperature plausible bounds from configuration using the `VOF_TEMP_*`
  naming convention (`VOF_TEMP_MIN`, `VOF_TEMP_MAX`), falling back to the `BodyTemperature` class
  `plausible_range` when unset.
- THE plausible-range validation SHALL apply the correct bounds per vital-sign class using the
  existing per-vital-class overrides map: temperature bounds (`VOF_TEMP_*`) SHALL apply only to
  body-temperature Readings, with no cross-application of one vital's bounds to another. The
  `PlausibleRangeValidator` ABC and construction surface SHALL NOT change beyond adding the new entry
  to the overrides map in the composition root.
- WHEN the Validator_Chain rejects a Reading, THE Pipeline SHALL log the rejection at `INFO` without
  the measurement value and SHALL NOT produce an Observation, unchanged from existing behavior.
- Duplicate detection for `BodyTemperature` SHALL reuse the existing scalar identity key
  (`device_id`, `effective`, `value`) with no change to the `DuplicateValidator`.

#### FR-TEMP-7 — API and CapabilityStatement coverage
*Traces to product FR-11 and ADR-0001.*

- THE API `GET /fhir/metadata` CapabilityStatement SHALL reflect that body-temperature Observations
  are searchable through the existing read-only endpoints.
- THE API `GET /fhir/Observation` search SHALL filter body-temperature Observations by their LOINC
  `code` using the existing `code` search parameter, with no new endpoint added.
- THE API SHALL continue to expose no write operation.

#### FR-TEMP-8 — Adapter selection for the thermometer
*Traces to product FR-13 and ADR-0001.*

- THE CLI adapter resolver SHALL map new short names for the Temp_Adapter and its mock counterpart
  alongside the existing `mock`, `miband10`, `bp`, `mock-bp`, `spo2`, and `mock-spo2` names.
- THE CLI SHALL continue to allow selecting any `DeviceAdapter` by fully qualified
  `package.module.ClassName`, so third-party thermometer adapters need no repository change.
- THE Pipeline SHALL provide a mock thermometer source so the temperature path (including out-of-range
  and Fahrenheit-normalization readings) can be exercised without hardware; the mock source SHALL NOT
  import `bleak`.

#### FR-TEMP-9 — Configuration surface checkpoint
*Traces to product NFR-6, `docs/brief-config-file.md`, and ADR-0001.*

- WHEN this slice adds `VOF_TEMP_*`, THE spec deliverables SHALL update the configuration-surface
  checkpoint in `docs/brief-config-file.md`: re-count the total `VOF_*` variables after `VOF_TEMP_*`
  lands and record an explicit judgment of whether the flat env-var list has become "awkward" enough
  to warrant promoting the optional `config.yaml` idea to its own spec.
- THE checkpoint update SHALL NOT itself build a config-file layer; it SHALL only record the count and
  the judgment, consistent with the brief's guardrails.

### Non-functional requirements

#### NFR-TEMP-1 — No breaking changes to the object model
*Traces to product NFR-6, the object-model conventions, and ADR-0001.*

- THE new vital-sign, parser, adapter, decoder, and validator-wiring changes SHALL be introduced by
  subclassing, composing, or additively extending the existing ABCs and modules, with no change to
  any existing ABC method signature or `__all__` public name.
- Adding the Float_Decoder SHALL add only new members to `adapters/sfloat.py`; it SHALL NOT alter the
  existing `decode_sfloat` signature or behavior, nor the `Validator` ABC.
- Any change that would alter an existing public ABC or exported name SHALL be treated as breaking and
  recorded in `CHANGELOG.md` with a `**Breaking:**` note; the intent of this spec is to avoid such
  changes.

#### NFR-TEMP-2 — Dependency directions preserved
*Traces to product NFR-6 and the structure steering doc.*

- After this spec is implemented, `uv run pytest tests/test_dependency_directions.py` SHALL pass,
  confirming no forbidden cross-package imports were introduced.
- THE `vitals` package (including `BodyTemperature`) SHALL continue to import no other
  `vitals_on_fhir` package. THE Float_Decoder SHALL live in `adapters` and add no cross-package import.

#### NFR-TEMP-3 — Interoperability
*Traces to product NFR-4.*

- THE Pipeline SHALL produce body-temperature Observations conforming to FHIR R4 (4.0.1) and the US
  Core Body Temperature profile, using LOINC and UCUM codings.
- THE Pipeline SHALL validate every generated resource with `fhir.resources` model validation before
  serving or storing it.
- THE domain model SHALL retain the LOINC and UCUM bindings as class metadata independent of FHIR, so
  a future non-FHIR target mapper can consume `BodyTemperature` objects without changes to the
  `vitals` package.

#### NFR-TEMP-4 — Provenance and licensing
*Traces to the security/provenance steering doc and product license rules.*

- Every source file added by this spec SHALL begin with `# SPDX-License-Identifier: AGPL-3.0-or-later`.
- Protocol knowledge for the HTS_Profile and the IEEE-11073 32-bit FLOAT SHALL be sourced only from
  published Bluetooth SIG, HL7/FHIR, or public IEEE/vendor specifications, and cited in `docs/`; no
  code SHALL be copied, translated, or closely paraphrased from other projects or vendor SDKs.
- WHERE any third-party or EviTrace-ported material is included, THE Pipeline SHALL record it in
  `NOTICE` with the required fields.

#### NFR-TEMP-5 — Security and privacy unchanged
*Traces to product NFR-5 and the security steering doc.*

- THE new type, parser, adapter, decoder, and validator-wiring changes SHALL NOT introduce any
  non-FHIR side channel for measurement data.
- THE Pipeline SHALL NOT include measurement values in log messages at `INFO` level or above, and
  SHALL NOT include `VOF_API_TOKEN` in any log message at any level.
- THE CLI SHALL continue to bind to `127.0.0.1` by default; this spec SHALL NOT introduce remote
  deployment.

#### NFR-TEMP-6 — Test coverage
*Traces to product NFR-6 and the testing steering doc.*

- THE test suite SHALL include: an `__init_subclass__` metadata test for `BodyTemperature`;
  Float_Decoder tests (including reserved/unusable values and negative exponent/mantissa), separate
  from the SFLOAT decoder tests; Temp_Parser tests covering well-formed Celsius and Fahrenheit
  payloads, the optional timestamp field, the optional temperature-type field length accounting, and
  malformed/short/reserved-FLOAT payloads; a mapper test asserting a valid US Core Body Temperature
  Observation (temperature value, `Cel` UCUM code, LOINC `8310-5`); validator tests confirming
  temperature bounds apply to body temperature and do not cross-apply to other vitals; and
  Temp_Adapter/`BleConnection` behavior tests. The fast suite SHALL pass without hardware.
- THE existing heart-rate, blood-pressure, and oxygen-saturation test suites (including the
  dependency-direction test) SHALL remain green, serving as the regression guardrail — in particular
  after the Float_Decoder is added to the shared module.
- Hardware-dependent tests for a real thermometer SHALL carry the `hardware` marker and be excluded
  from CI, consistent with the MVP convention.

---

## Out of scope

Per the product steering document and ADR-0001, this spec excludes:

- The HTS **Intermediate Temperature** characteristic (`0x2A1E`) and its notification-based delivery —
  deferred; this slice acquires only the (indication-based) Temperature Measurement stream. If added
  later, it can reuse the same parser and the shared `start_notify` path but is its own slice, mirror
  of how SpO2 deferred the spot-check characteristic.
- Modelling the optional temperature-type field (e.g. body site) as structured Observation data (may
  be added later, additively, without changing this spec's output).
- Body weight — deferred to its own phase-2 sibling spec.
- Multiple simultaneous connected devices (still one device at a time).
- Persistence beyond in-memory storage (no database, disk, or remote store) — phase 4.
- Remote or cloud deployment and exposure to untrusted networks.
- SMART on FHIR authentication and outbound FHIR sinks — phase 4; not stubbed or referenced here.
- Phone health aggregators (Health Connect, HealthKit) — phase 3.
- Proprietary or reverse-engineered device protocols and any circumvention of device security.
- Writing to external EHRs or FHIR servers, and any write operation on the local API.
- Building the `docs/brief-config-file.md` `config.yaml` layer; this spec adds `VOF_TEMP_*` as flat
  env vars and updates the surface-size checkpoint in that brief, but does not build a config-file
  layer.
