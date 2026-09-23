# Requirements Document

**Spec: oxygen-saturation** (pulse oximetry — second phase-2 slice)

## Introduction

This spec is the second sibling in roadmap phase 2 (home health devices), following
`home-health-devices` (blood pressure). It adds acquisition of peripheral oxygen saturation (SpO2)
from a standard Bluetooth **Pulse Oximeter** (the PLX profile) and represents each reading as an
HL7 FHIR R4 Observation conforming to the US Core Pulse Oximetry profile.

Phase 2 is delivered as a series of sibling specs, one per profile, to keep each reviewable and
landable on its own (see `docs/adr-0001-open-phase-2-home-health-devices.md`). **This spec covers
oxygen saturation only.** Body temperature and body weight remain deferred to their own sibling
specs.

Unlike blood pressure — which introduced the first `ComponentVital` — oxygen saturation is a single
scalar percentage. It therefore lands as a new **`ScalarVital`** subclass, exactly as ADR-0001
anticipated ("new `ScalarVital` types (pulse oximetry / oxygen saturation, ...)"). Because the
blood-pressure slice already extracted the reusable `BleConnection` lifecycle and the
`ScalarVitalMapper` already builds an Observation from a scalar vital's class metadata, **this slice
needs no new FHIR mapper code and no new BLE lifecycle** — it reuses both. That reuse is the payoff
of ordering blood pressure first, and it narrows this spec's new surface to: a new `ScalarVital`, a
new PLX payload parser (with shared SFLOAT decoding), a new adapter composing the existing lifecycle,
a per-vital-class generalization of the plausible-range validator, config, a mock source, and docs.

### Why this profile is more involved than heart rate

The Pulse Oximeter (PLX) profile is more intricate than the Heart Rate Service in three ways, all of
which this spec addresses or explicitly bounds:

1. **SFLOAT value encoding.** SpO2 and pulse rate are IEEE-11073 16-bit SFLOATs, the same encoding
   blood pressure uses — not the plain uint8/uint16 of heart rate. This spec reuses the SFLOAT
   decoding introduced for blood pressure rather than re-deriving it.
2. **Two measurement characteristics.** PLX defines a **Spot-Check Measurement** characteristic
   (`0x2A5E`, typically delivered via GATT *indications*) and a **Continuous Measurement**
   characteristic (`0x2A5F`, via *notifications*). This slice targets the **Continuous Measurement**
   characteristic, which maps directly onto the existing notification-driven `BleConnection`
   lifecycle. Spot-check acquisition is deferred (see Out of scope) so this slice needs no change to
   the shared lifecycle.
3. **Optional fields.** The PLX measurement carries an optional pulse-rate SFLOAT and optional status
   and device-and-sensor-status fields. This spec decodes only the SpO2 value; other fields are
   accounted for in length calculations but not modelled (pulse rate may be added additively later,
   as its own `ScalarVital`, without changing this spec's output).

### Relationship to the blood-pressure slice

- **Reuses** the `BleConnection` lifecycle (unchanged), the `ScalarVitalMapper` (unchanged), the
  `DuplicateValidator` (unchanged — its scalar identity key already covers SpO2), and the
  `SensorContactValidator` (unchanged — it passes non-heart-rate vitals through).
- **Generalizes** `PlausibleRangeValidator` so per-vital-class bounds are possible. Today it applies a
  single `(min, max)` override to *every* `ScalarVital`. With two scalar vitals (heart rate and SpO2)
  in the chain, one instance cannot carry both bounds; the validator is generalized to look up bounds
  per vital class, falling back to each class's `plausible_range`. This is an additive change to a
  concrete validator (not an ABC) — see NFR-SPO2-1.
- **Adds** SFLOAT decoding as a shared pure-function module in `adapters/`, used by both the
  blood-pressure and pulse-oximeter parsers, so the IEEE-11073 logic exists once.

### Design note carried forward — device timestamp timezone

The blood-pressure slice interprets a device's zoneless timestamp as host local time and returns it
timezone-aware (documented in `docs/protocol-blood-pressure-measurement.md` and
`docs/brief-config-file.md`). The PLX Continuous Measurement characteristic **does not carry a
timestamp** (only Spot-Check does), so a continuous SpO2 reading's `effective` time is the processing
time (`now()`), timezone-aware. This spec therefore introduces no new timezone behavior; the
store-and-forward path introduced for blood pressure is unaffected and unused here. If spot-check
acquisition is added later, its timestamp handling SHALL reuse the blood-pressure convention.

### Numbering

The decision to open phase 2 is recorded in `docs/adr-0001-open-phase-2-home-health-devices.md`.
New functional (**FR-SPO2-\***) and non-functional (**NFR-SPO2-\***) requirement IDs are additive and
distinct from the blood-pressure slice's `FR-HH-*`/`NFR-HH-*` IDs, so each sibling spec's traceability
stays unambiguous for the planned preprint. Existing MVP and blood-pressure IDs are preserved and not
renumbered. Acceptance criteria follow EARS patterns, mirroring the style of the sibling specs.

## Glossary

- **Pipeline**: the end-to-end vitals-on-fhir system (adapter → validators → mapper → sinks).
- **PLX_Profile**: the standard Bluetooth SIG Pulse Oximeter Service (GATT service UUID `0x1822`).
- **PLX_Continuous_Characteristic**: the PLX Continuous Measurement characteristic (GATT `0x2A5F`).
- **PLX_Spot_Check_Characteristic**: the PLX Spot-Check Measurement characteristic (GATT `0x2A5E`);
  out of scope for this slice.
- **SpO2_Adapter**: the concrete `DeviceAdapter` acquiring readings over the PLX_Profile.
- **SpO2_Parser**: the `GattCharacteristicParser` subclass decoding a PLX_Continuous_Characteristic
  payload into an `OxygenSaturation` domain object.
- **SFLOAT**: the IEEE-11073 16-bit short-float encoding (4-bit signed exponent, 12-bit signed
  mantissa) used for the SpO2 value, with reserved values (NaN, NRes, ±INFINITY) that are not usable.
- **SFLOAT_Decoder**: the shared pure-function SFLOAT decoding used by both the blood-pressure and
  pulse-oximeter parsers.
- **OxygenSaturation**: the new `ScalarVital` subclass carrying a single SpO2 percentage value.
- **Scalar_Mapper**: the existing `ScalarVitalMapper`, reused unchanged by this spec.
- **Validator_Chain**: the `ValidatorChain` running validators in registration order.
- **Reading**: a single decoded, well-formed `OxygenSaturation` measurement.
- **Observation**: a `fhir.resources` R4 `Observation` model instance.
- **CLI**: `cli.py`, the composition root — the only module that instantiates concrete classes.

---

## Requirements

### Functional requirements

#### FR-SPO2-1 — Oxygen-saturation vital-sign type
*Traces to product FR-13 (extensibility), the object-model `ScalarVital` contract, and ADR-0001.*

- THE Pipeline SHALL define `OxygenSaturation` as a frozen `ScalarVital` subclass under
  `vitals/builtin/`, carrying the SpO2 percentage as its single numeric `value`.
- THE `OxygenSaturation` type SHALL declare its `loinc_code` (`59408-5`, oxygen saturation in
  arterial blood by pulse oximetry), its `us_core_profile` (the US Core Pulse Oximetry profile),
  its `ucum_unit` (`%`), and a default `plausible_range`.
- WHERE `OxygenSaturation` omits required class metadata, THE Pipeline SHALL raise at import time,
  consistent with the existing `VitalSign`/`ScalarVital` metadata-enforcement contract.
- THE `OxygenSaturation` type SHALL be exported from `vitals/__init__.py` under `# Concrete defaults`.
- Introducing `OxygenSaturation` SHALL NOT change any existing public ABC method signature or
  exported name.

#### FR-SPO2-2 — Shared SFLOAT decoding
*Traces to product FR-3 (parsing), NFR-6 (maintainability), and ADR-0001.*

- THE Pipeline SHALL provide IEEE-11073 16-bit SFLOAT decoding as a pure function usable by more than
  one parser, so the blood-pressure and pulse-oximeter parsers share one implementation of the
  encoding rather than duplicating it.
- THE SFLOAT_Decoder SHALL treat reserved mantissa values (NaN, NRes, +INFINITY, −INFINITY, and the
  reserved value) as not representing a usable number, returning a sentinel the caller drops on.
- THE SFLOAT_Decoder SHALL reside in the `adapters` package and SHALL depend only on the Python
  standard library, introducing no new cross-package dependency.
- Consolidating SFLOAT decoding SHALL preserve the blood-pressure parser's existing behavior: the
  full existing test suite SHALL remain green.

#### FR-SPO2-3 — PLX Continuous Measurement payload parsing
*Traces to product FR-3 (parsing) and ADR-0001.*

- WHEN the SpO2_Parser receives a PLX_Continuous_Characteristic payload, THE SpO2_Parser SHALL decode
  the flags byte and the SpO2 SFLOAT field per the Bluetooth SIG PLX Continuous Measurement
  specification, using the SpO2 value to construct the Reading.
- THE SpO2_Parser SHALL account for the optional pulse-rate SFLOAT and the optional measurement-status
  and device-and-sensor-status fields when computing the minimum payload length, even though only the
  SpO2 value is used.
- IF a payload is too short for the fields its flags byte declares, or the SpO2 SFLOAT is a
  reserved/unusable value, THEN THE SpO2_Parser SHALL return `None` and THE SpO2_Adapter SHALL drop it
  without yielding a Reading.
- THE SpO2_Parser SHALL set the Reading's `effective` time to the current time (timezone-aware), since
  the Continuous Measurement characteristic carries no timestamp; the clock SHALL be injectable for
  tests.
- THE SpO2_Parser byte-level decoding SHALL be implemented as pure functions the parser class
  delegates to, consistent with the existing heart-rate and blood-pressure parsers, and SHALL use the
  shared SFLOAT_Decoder.
- THE `docs/` directory SHALL cite the Bluetooth SIG Pulse Oximeter Service / PLX Continuous
  Measurement specification (name, version, and URL or publication date) used to implement the parser.

#### FR-SPO2-4 — BLE acquisition via the shared lifecycle
*Traces to product FR-1, FR-2, FR-13, and ADR-0001.*

- THE SpO2_Adapter SHALL acquire readings over the PLX_Profile by composing the existing reusable BLE
  lifecycle (`BleConnection`), configured with the PLX_Profile service UUID (`0x1822`) and the
  PLX_Continuous_Characteristic UUID (`0x2A5F`), delegating payload decoding to the SpO2_Parser.
- THE SpO2_Adapter SHALL reuse the shared lifecycle **by composition without modifying it**, keeping
  every concrete adapter within the object-model 3-level inheritance cap.
- THE SpO2_Adapter and the shared lifecycle SHALL import `bleak` lazily inside the methods that use
  it, never at module level, consistent with the existing BLE rule.
- WHEN a notification is received on the subscribed characteristic, THE SpO2_Adapter SHALL pass the
  payload to the SpO2_Parser and yield the resulting Reading from its `vitals()` async generator
  without user intervention.
- THE Pipeline SHALL continue to support exactly one connected device at a time (unchanged from MVP).

#### FR-SPO2-5 — FHIR mapping via the existing scalar mapper
*Traces to product FR-4, FR-8, NFR-4, and ADR-0001.*

- WHEN an `OxygenSaturation` Reading is accepted, THE Pipeline SHALL convert it to a FHIR R4
  `Observation` conforming to the US Core Pulse Oximetry profile, reusing the existing Scalar_Mapper
  with **no new mapper code**.
- THE resulting Observation SHALL carry `status` `final`, the vital-signs `category`, the panel `code`
  from the vital's `loinc_code` (`59408-5`), and a `valueQuantity` whose UCUM `code` is `%` and whose
  value is the SpO2 percentage.
- THE Observation SHALL be constructed using `fhir.resources` model classes so model validation runs
  at construction time; IF construction fails validation, THEN THE Pipeline SHALL log at `ERROR`
  (without the measurement value) and SHALL NOT serve or store the Observation.
- THE mapper registry SHALL resolve `OxygenSaturation` to the Scalar_Mapper by MRO walk, leaving both
  `HeartRate → ScalarVitalMapper` and `BloodPressure → ComponentVitalMapper` resolution unchanged.

#### FR-SPO2-6 — Per-vital-class plausibility validation
*Traces to product FR-3 (validation) and ADR-0001.*

- THE Pipeline SHALL validate an `OxygenSaturation` Reading by checking its value against a plausible
  SpO2 range, rejecting the Reading if the value is out of range.
- THE Pipeline SHALL source the SpO2 plausible bounds from configuration using the `VOF_SPO2_*` naming
  convention (`VOF_SPO2_MIN`, `VOF_SPO2_MAX`), falling back to the `OxygenSaturation` class
  `plausible_range` when unset.
- THE plausible-range validation SHALL apply the correct bounds per vital-sign class: heart-rate
  bounds (`VOF_HR_*`) SHALL apply only to heart-rate Readings and SpO2 bounds (`VOF_SPO2_*`) only to
  SpO2 Readings, with no cross-application of one vital's bounds to another.
- WHEN the Validator_Chain rejects a Reading, THE Pipeline SHALL log the rejection at `INFO` without
  the measurement value and SHALL NOT produce an Observation, unchanged from existing behavior.
- Duplicate detection for `OxygenSaturation` SHALL reuse the existing scalar identity key
  (`device_id`, `effective`, `value`) with no change to the `DuplicateValidator`.

#### FR-SPO2-7 — API and CapabilityStatement coverage
*Traces to product FR-11 and ADR-0001.*

- THE API `GET /fhir/metadata` CapabilityStatement SHALL reflect that oxygen-saturation Observations
  are searchable through the existing read-only endpoints.
- THE API `GET /fhir/Observation` search SHALL filter oxygen-saturation Observations by their LOINC
  `code` using the existing `code` search parameter, with no new endpoint added.
- THE API SHALL continue to expose no write operation.

#### FR-SPO2-8 — Adapter selection for the pulse oximeter
*Traces to product FR-13 and ADR-0001.*

- THE CLI adapter resolver SHALL map new short names for the SpO2_Adapter and its mock counterpart
  alongside the existing `mock`, `miband10`, `bp`, and `mock-bp` names.
- THE CLI SHALL continue to allow selecting any `DeviceAdapter` by fully qualified
  `package.module.ClassName`, so third-party pulse-oximeter adapters need no repository change.
- THE Pipeline SHALL provide a mock pulse-oximeter source so the SpO2 path (including out-of-range
  readings) can be exercised without hardware; the mock source SHALL NOT import `bleak`.

### Non-functional requirements

#### NFR-SPO2-1 — No breaking changes to the object model
*Traces to product NFR-6, the object-model conventions, and ADR-0001.*

- THE new vital-sign, parser, adapter, and validator changes SHALL be introduced by subclassing or
  composing the existing ABCs, with no change to any existing ABC method signature or `__all__`
  public name.
- Generalizing `PlausibleRangeValidator` to per-vital-class bounds SHALL remain backward compatible:
  existing construction with a single `(min, max)` pair SHALL continue to work, and the change SHALL
  add only new members. It SHALL NOT alter the `Validator` ABC.
- Any change that would alter an existing public ABC or exported name SHALL be treated as breaking and
  recorded in `CHANGELOG.md` with a `**Breaking:**` note; the intent of this spec is to avoid such
  changes.

#### NFR-SPO2-2 — Dependency directions preserved
*Traces to product NFR-6 and the structure steering doc.*

- After this spec is implemented, `uv run pytest tests/test_dependency_directions.py` SHALL pass,
  confirming no forbidden cross-package imports were introduced.
- THE `vitals` package (including `OxygenSaturation`) SHALL continue to import no other
  `vitals_on_fhir` package. THE shared SFLOAT_Decoder SHALL live in `adapters` and add no
  cross-package import.

#### NFR-SPO2-3 — Interoperability
*Traces to product NFR-4.*

- THE Pipeline SHALL produce oxygen-saturation Observations conforming to FHIR R4 (4.0.1) and the US
  Core Pulse Oximetry profile, using LOINC and UCUM codings.
- THE Pipeline SHALL validate every generated resource with `fhir.resources` model validation before
  serving or storing it.
- THE domain model SHALL retain the LOINC and UCUM bindings as class metadata independent of FHIR, so
  a future non-FHIR target mapper can consume `OxygenSaturation` objects without changes to the
  `vitals` package.

#### NFR-SPO2-4 — Provenance and licensing
*Traces to the security/provenance steering doc and product license rules.*

- Every source file added by this spec SHALL begin with `# SPDX-License-Identifier: AGPL-3.0-or-later`.
- Protocol knowledge for the PLX_Profile SHALL be sourced only from published Bluetooth SIG, HL7/FHIR,
  or public vendor specifications, and cited in `docs/`; no code SHALL be copied, translated, or
  closely paraphrased from other projects or vendor SDKs.
- WHERE any third-party or EviTrace-ported material is included, THE Pipeline SHALL record it in
  `NOTICE` with the required fields.

#### NFR-SPO2-5 — Security and privacy unchanged
*Traces to product NFR-5 and the security steering doc.*

- THE new type, parser, adapter, and validator changes SHALL NOT introduce any non-FHIR side channel
  for measurement data.
- THE Pipeline SHALL NOT include measurement values in log messages at `INFO` level or above, and
  SHALL NOT include `VOF_API_TOKEN` in any log message at any level.
- THE CLI SHALL continue to bind to `127.0.0.1` by default; this spec SHALL NOT introduce remote
  deployment.

#### NFR-SPO2-6 — Test coverage
*Traces to product NFR-6 and the testing steering doc.*

- THE test suite SHALL include: an `__init_subclass__` metadata test for `OxygenSaturation`;
  SFLOAT_Decoder tests (including reserved/unusable values), shared by construction with the
  blood-pressure parser; SpO2_Parser tests covering well-formed payloads, the optional-field length
  accounting, and malformed/short/reserved-SFLOAT payloads; a mapper test asserting a valid US Core
  Pulse Oximetry Observation (SpO2 value, `%` UCUM code, LOINC `59408-5`); validator tests confirming
  SpO2 bounds apply to SpO2 and heart-rate bounds do not cross-apply; and SpO2_Adapter/`BleConnection`
  behavior tests. The fast suite SHALL pass without hardware.
- THE existing heart-rate and blood-pressure test suites (including the dependency-direction test)
  SHALL remain green, serving as the regression guardrail — in particular after SFLOAT decoding is
  consolidated and `PlausibleRangeValidator` is generalized.
- Hardware-dependent tests for a real pulse oximeter SHALL carry the `hardware` marker and be excluded
  from CI, consistent with the MVP convention.

---

## Out of scope

Per the product steering document and ADR-0001, this spec excludes:

- The PLX **Spot-Check Measurement** characteristic (`0x2A5E`) and its indication-based delivery and
  embedded timestamp — deferred; this slice acquires only the Continuous Measurement stream.
- Modelling the optional PLX **pulse-rate** field as a vital sign (may be added later, additively, as
  its own `ScalarVital` without changing this spec's output).
- Body temperature and body weight — deferred to their own phase-2 sibling specs.
- Multiple simultaneous connected devices (still one device at a time).
- Persistence beyond in-memory storage (no database, disk, or remote store) — phase 4.
- Remote or cloud deployment and exposure to untrusted networks.
- SMART on FHIR authentication and outbound FHIR sinks — phase 4; not stubbed or referenced here.
- Phone health aggregators (Health Connect, HealthKit) — phase 3.
- Proprietary or reverse-engineered device protocols and any circumvention of device security.
- Writing to external EHRs or FHIR servers, and any write operation on the local API.
- Promotion of the `docs/brief-config-file.md` `config.yaml` idea; this spec adds `VOF_SPO2_*` as flat
  env vars and updates the surface-size checkpoint recorded in that brief, but does not build a config
  file layer.
