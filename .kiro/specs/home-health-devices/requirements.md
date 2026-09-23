# Requirements Document

**Spec: home-health-devices**

## Introduction

This spec opens roadmap phase 2: acquiring vital signs from home health devices over
**standard Bluetooth health profiles**, and representing each as an HL7 FHIR R4 Observation.
It extends the proven heart-rate pipeline (`hr-pipeline`) using the same extension points —
new `VitalSign` subclasses, new `DeviceAdapter`/parser subclasses, new validators — without
breaking changes to the object model.

Phase 2 is delivered as a series of sibling specs, one per profile, to keep each reviewable and
landable on its own. **This spec covers blood pressure only.** It introduces `BloodPressure` as
the **first concrete `ComponentVital`**, activating the `ComponentVital` / `ComponentVitalMapper`
half of the object model that the MVP left as a documented stub. Oxygen saturation (pulse
oximetry), body temperature, and body weight are deferred to their own sibling specs; the pulse
oximeter profile in particular is more complex (SFLOAT encoding, spot-check vs continuous) and
warrants separate treatment.

This spec also generalizes BLE acquisition beyond the Heart Rate Service and adds first-class
**store-and-forward** handling, where a reading's measurement time (`effective`) differs from its
processing time (`issued`) — which blood-pressure cuffs commonly produce, since a cuff completes a
measurement and then notifies.

### "Continuous monitoring" for intermittent devices

Product **FR-7** requires continuous monitoring. Blood-pressure cuffs are intermittent: they
measure, notify once, then go quiet until the next measurement. To serve both streaming devices
(a heart-rate strap) and intermittent ones (a cuff) with the same pipeline and no special-casing,
this spec defines "continuous" as **device-rate delivery without added latency**, not a fixed
system cadence: the Pipeline delivers every Reading the device exposes, as promptly as the device
exposes it, and the interval between Readings is a property of the device, not of the Pipeline.
Liveness is kept separate from cadence — the dashboard reflects the adapter's connection state and
does not treat silence between Readings as a disconnection. This is consistent with the MVP, whose
dashboard status is already driven by `ConnectionState` transitions rather than a reading timeout,
so the requirement documents existing behavior as correct for intermittent devices rather than
adding logic.

### Design note for future agents — connectionless adapters

The liveness rule below is deliberately scoped to **connection-oriented adapters** (any BLE
adapter, including the BP_Adapter, holds a persistent BLE connection and stays subscribed between
readings, so `ConnectionState` is meaningful during quiet intervals). A future intermittent source
with **no persistent connection** — for example a file-drop adapter or a phone-aggregator adapter
(roadmap phase 3) — has no meaningful `CONNECTED`/`DISCONNECTED` distinction between readings.
Do **not** assume the connection-state liveness model transfers to such sources; connectionless
adapters will need their own liveness/staleness semantics (e.g. a last-seen freshness window),
which is out of scope here and left to the spec that introduces the first connectionless adapter.
This hypothesis is recorded so it need not be re-derived.

### Resolved design decisions

These were agreed during requirements review and constrain the design:

- **Component model (Option A).** A `ComponentVital` declares its component *structure* as typed
  class metadata (each component a `(loinc_code, ucum_unit, field_name)` spec) and carries the
  *values* as named, typed instance fields (e.g. `systolic`, `diastolic`). This mirrors how
  `ScalarVital` uses class metadata plus an instance `value`, keeps the domain model strongly
  typed and FHIR-free, and keeps LOINC/UCUM semantics in the target-neutral domain layer so a
  future non-FHIR mapper (e.g. OMOP/openEHR) is a thin loop over declared components rather than a
  rewrite.
- **Mean arterial pressure (MAP) is omitted.** MAP is device-derived, not independently measured;
  `BloodPressure` models systolic + diastolic only. MAP can be added later as an additive third
  component spec with no ABC change.
- **Generalized BLE via composition.** The profile-agnostic BLE lifecycle (scan, connect,
  subscribe, threadsafe-queue handoff, reconnect with backoff, disconnect) is factored into a
  shared, reusable unit that concrete adapters *use by composition*, not a new inheritance level —
  respecting the object-model 3-level inheritance cap and its "composition over inheritance"
  preference. Extraction preserves the existing public surface of `BleHeartRateAdapter`.

The decision to open phase 2 is recorded in `docs/adr-0001-open-phase-2-home-health-devices.md`.
Each requirement below is traced to that ADR and to the product steering document. New
functional (FR-HH-*) and non-functional (NFR-HH-*) requirement IDs are **additive**; existing MVP
FR-/NFR- IDs are preserved and not renumbered, for the planned preprint. Acceptance criteria
follow EARS patterns and INCOSE quality rules, mirroring the style of `hr-pipeline/requirements.md`.

## Glossary

- **Pipeline**: the end-to-end vitals-on-fhir system (adapter → validators → mapper → sinks).
- **BP_Profile**: the standard Bluetooth SIG Blood Pressure Service (GATT service UUID `0x1810`).
- **BP_Measurement_Characteristic**: the Blood Pressure Measurement characteristic (GATT `0x2A35`).
- **BLE_Lifecycle**: the profile-agnostic BLE scan/connect/subscribe/reconnect/disconnect unit
  reused by composition across BLE adapters.
- **BP_Adapter**: the concrete `DeviceAdapter` acquiring readings over the BP_Profile.
- **BP_Parser**: the `GattCharacteristicParser` subclass decoding a BP_Measurement_Characteristic
  payload into a `BloodPressure` domain object.
- **Component_Vital**: a `ComponentVital` subclass — a multi-component measurement (blood pressure).
- **Component_Spec**: the typed class-level descriptor binding a component to its `loinc_code`,
  `ucum_unit`, and the instance field name that carries its value.
- **Component_Mapper**: the `ComponentVitalMapper` converting a Component_Vital to an Observation.
- **Scalar_Mapper**: the existing `ScalarVitalMapper`, unchanged by this spec.
- **Validator_Chain**: the `ValidatorChain` running validators in registration order.
- **Store**: the `InMemoryObservationStore` (both `ObservationStore` and `ObservationSink`).
- **Reading**: a single decoded, well-formed `BloodPressure` measurement.
- **Observation**: a `fhir.resources` R4 `Observation` model instance.
- **Effective_Time**: the timezone-aware time a measurement was taken (`effective` field).
- **Issued_Time**: the timezone-aware time a measurement was processed (`issued` field).
- **Store_And_Forward**: the case where Effective_Time precedes Issued_Time (a buffered reading).
- **CLI**: `cli.py`, the composition root — the only module that instantiates concrete classes.

---

## Requirements

### Functional requirements

#### FR-HH-1 — Component-vital domain shape
*Traces to product FR-13 (extensibility), the object-model `ComponentVital` contract, and ADR-0001.*

- THE Pipeline SHALL define the concrete shape of the `ComponentVital` ABC such that a subclass
  declares its component structure as class-level metadata (an ordered collection of Component_Specs)
  and carries each component value as a named, typed instance field.
- Each Component_Spec SHALL bind a component to a `loinc_code`, a `ucum_unit`, and the name of the
  instance field that carries its value.
- THE Component_Spec type SHALL live in the `vitals` package and SHALL NOT import FHIR, adapter,
  validation, or any other `vitals_on_fhir` package, preserving the domain layer's independence.
- WHERE a concrete `ComponentVital` subclass omits its component structure, panel `loinc_code`, or
  `us_core_profile`, THE Pipeline SHALL raise at import time (via `__init_subclass__`), consistent
  with the existing `VitalSign` metadata-enforcement contract.
- THE `ComponentVital` shape SHALL be additive: introducing it SHALL NOT change any existing public
  ABC method signature or exported name.

#### FR-HH-2 — Blood pressure vital-sign type
*Traces to product FR-13, the object-model `ComponentVital` contract, and ADR-0001.*

- THE Pipeline SHALL define `BloodPressure` as a frozen `ComponentVital` subclass under
  `vitals/builtin/`, carrying `systolic` and `diastolic` as named numeric instance fields.
- THE `BloodPressure` type SHALL declare its panel `loinc_code` (`85354-9`), its `us_core_profile`
  (the US Core Blood Pressure profile), and two Component_Specs: systolic (LOINC `8480-6`) and
  diastolic (LOINC `8462-4`), both with UCUM unit `mm[Hg]`.
- THE `BloodPressure` type SHALL NOT include a mean-arterial-pressure component in this spec.
- WHERE `BloodPressure` omits required class or component metadata, THE Pipeline SHALL raise at
  import time.
- THE `BloodPressure` type SHALL be exported from `vitals/__init__.py` under `# Concrete defaults`.

#### FR-HH-3 — Component FHIR mapping
*Traces to product FR-4, FR-8, NFR-4, and ADR-0001. Activates the roadmap stub.*

- WHEN a Component_Vital is accepted, THE Component_Mapper SHALL convert it to a FHIR R4
  `Observation` conforming to the vital's declared US Core profile.
- THE Component_Mapper SHALL set `status` to `final`, the vital-signs `category` coding, and the
  panel `code` from the vital's panel `loinc_code`.
- THE Component_Mapper SHALL emit one `component` entry per Component_Spec, each with its component
  LOINC `code` and a `valueQuantity` carrying the UCUM system, unit code, and the numeric value read
  from the named instance field.
- THE Component_Mapper SHALL NOT set a panel-level `valueQuantity`, consistent with the US Core
  Blood Pressure profile, which carries values only in `component` entries.
- THE Component_Mapper SHALL set `subject`, `device`, `effectiveDateTime`, `issued`, a v4 UUID `id`,
  and `meta.profile` on the same basis as the Scalar_Mapper.
- THE Component_Mapper SHALL construct the Observation using `fhir.resources` model classes so that
  model validation runs at construction time.
- IF Observation construction fails validation, THEN THE Pipeline SHALL log the failure at `ERROR`
  level (without measurement values) and SHALL NOT serve or store an invalid Observation.
- THE mapper registry SHALL resolve the Component_Mapper for `ComponentVital` subclasses by walking
  the MRO, leaving `ScalarVital` → Scalar_Mapper resolution unchanged.

#### FR-HH-4 — Generalized BLE acquisition via a shared lifecycle
*Traces to product FR-1, FR-2, FR-13, and ADR-0001.*

- THE Pipeline SHALL provide a reusable BLE_Lifecycle that scans for, connects to, subscribes to,
  and reconnects to a configured GATT service/characteristic, without hardcoding the Heart Rate
  Service UUIDs or the heart-rate parser.
- THE BLE_Lifecycle SHALL be reused by composition: concrete BLE adapters SHALL delegate their
  connection lifecycle to it rather than inheriting a new base class level, keeping every concrete
  adapter within the object-model 3-level inheritance cap.
- Extracting the BLE_Lifecycle SHALL preserve the existing public surface of `BleHeartRateAdapter`
  (its exported name, its `matches`/`device_info` abstract members, and its constructor signature);
  the existing heart-rate adapter and `MiBand10Adapter` SHALL continue to function unchanged.
- THE BP_Adapter SHALL declare the BP_Profile service UUID (`0x1810`) and the
  BP_Measurement_Characteristic UUID (`0x2A35`), and SHALL delegate payload decoding to the BP_Parser.
- THE BLE_Lifecycle and BP_Adapter SHALL import `bleak` lazily inside the methods that use it, never
  at module level, consistent with the existing BLE rule.
- WHEN a notification is received on the subscribed characteristic, THE BP_Adapter SHALL pass the
  payload to the BP_Parser and yield the resulting Reading from its `vitals()` async generator
  without user intervention.
- WHEN a BLE notification arrives on a thread other than the event loop, THE BLE_Lifecycle SHALL
  hand the payload to the event loop safely (for example via `loop.call_soon_threadsafe`) rather
  than performing async work in the callback thread.
- THE Pipeline SHALL continue to support exactly one connected device at a time (unchanged from MVP).

#### FR-HH-5 — Blood Pressure Measurement payload parsing
*Traces to product FR-3 (parsing) and ADR-0001.*

- WHEN the BP_Parser receives a payload, THE BP_Parser SHALL decode the flags byte and the systolic,
  diastolic, and mean-arterial-pressure SFLOAT fields per the Bluetooth SIG Blood Pressure
  Measurement specification, using only the systolic and diastolic values to construct the Reading.
- WHERE the flags byte indicates the measurement unit is kPa rather than mmHg, THE BP_Parser SHALL
  normalize the systolic and diastolic values to `mm[Hg]` before constructing the Reading.
- WHERE the payload carries the optional timestamp field, THE BP_Parser SHALL use it as the
  Reading's Effective_Time; otherwise THE BP_Parser SHALL use the current time.
- IF a payload is too short for the fields its flags byte declares, or is otherwise malformed, THEN
  THE BP_Parser SHALL return `None` and THE BP_Adapter SHALL drop it without yielding a Reading.
- THE BP_Parser byte-level decoding, including SFLOAT decoding, SHALL be implemented as pure
  functions the parser class delegates to, consistent with the existing heart-rate parser.
- THE `docs/` directory SHALL cite the Bluetooth SIG Blood Pressure Service / Blood Pressure
  Measurement specification (name, version, and URL or publication date) used to implement the parser.

#### FR-HH-6 — Store-and-forward and device-rate delivery
*Traces to product FR-4 (effective vs issued), FR-6 (connection status), FR-7 (continuous
monitoring), the object-model `VitalSign` contract, and ADR-0001.*

- WHERE a Reading's Effective_Time precedes its Issued_Time, THE Pipeline SHALL preserve both times
  distinctly, setting `effectiveDateTime` from Effective_Time and `issued` from Issued_Time.
- THE Pipeline SHALL require Effective_Time to be timezone-aware for every Reading, consistent with
  the `VitalSign` contract; a naive timestamp SHALL NOT be accepted.
- WHEN Store_And_Forward Readings arrive out of measurement order, THE Store SHALL retain them and
  THE API SHALL order them by `effectiveDateTime` when `_sort=-date` is requested.
- THE Pipeline SHALL deliver each Reading at the maximum frequency the device exposes it,
  introducing no buffering delay of its own; the interval between Readings SHALL be treated as a
  characteristic of the device, not a limitation of the Pipeline (refines product FR-7).
- WHERE the adapter is connection-oriented (holds a persistent connection, as every BLE adapter
  does), THE Dashboard SHALL derive connection status from the adapter's Connection_State and SHALL
  NOT infer disconnection from the absence of a new Reading; WHILE connected, THE Dashboard SHALL
  continue to display the most recent Reading during intervals when the device emits none (refines
  product FR-6, FR-7). Connectionless adapters are out of scope for this rule — see the design note
  in the Introduction.

#### FR-HH-7 — Validation for blood pressure
*Traces to product FR-3 (validation) and ADR-0001.*

- THE Pipeline SHALL validate a `BloodPressure` Reading by checking the systolic and diastolic
  components against their configured plausible bounds, rejecting the Reading if either is out of
  range.
- THE Pipeline SHALL source the systolic and diastolic plausible bounds from configuration using the
  `VOF_BP_*` naming convention (`VOF_BP_SYSTOLIC_MIN`, `VOF_BP_SYSTOLIC_MAX`, `VOF_BP_DIASTOLIC_MIN`,
  `VOF_BP_DIASTOLIC_MAX`), falling back to the component class metadata bounds when unset.
- WHEN the Validator_Chain rejects a Reading, THE Pipeline SHALL log the rejection at `INFO` without
  the measurement value and SHALL NOT produce an Observation, unchanged from the MVP behavior.

#### FR-HH-8 — API and CapabilityStatement coverage
*Traces to product FR-11 and ADR-0001.*

- THE API `GET /fhir/metadata` CapabilityStatement SHALL reflect that blood-pressure Observations are
  searchable through the existing read-only endpoints.
- THE API `GET /fhir/Observation` search SHALL filter blood-pressure Observations by their panel
  LOINC `code` using the existing `code` search parameter, with no new endpoint added.
- THE API SHALL continue to expose no write operation.

#### FR-HH-9 — Adapter selection for the blood-pressure device
*Traces to product FR-13 and ADR-0001.*

- THE CLI adapter resolver SHALL map a new short name for the BP_Adapter alongside the existing
  `mock` and `miband10` names.
- THE CLI SHALL continue to allow selecting any `DeviceAdapter` by fully qualified
  `package.module.ClassName`, so third-party BP adapters need no repository change.
- THE Mock_Adapter capability SHALL be extended, or a mock blood-pressure source provided, so the
  blood-pressure path (including out-of-range and store-and-forward cases) can be exercised without
  hardware; the mock source SHALL NOT import `bleak`.

### Non-functional requirements

#### NFR-HH-1 — No breaking changes to the object model
*Traces to product NFR-6, the object-model conventions, and ADR-0001.*

- THE new vital-sign, adapter, parser, and mapper additions SHALL be introduced by subclassing or
  composing the existing ABCs, with no change to any existing ABC method signature or `__all__`
  public name.
- Fleshing out the `ComponentVital` ABC shape SHALL add only new members; it SHALL NOT alter the
  existing `VitalSign` or `ScalarVital` public surface.
- Any change that would alter an existing public ABC or exported name SHALL be treated as breaking,
  recorded in `CHANGELOG.md` with a `**Breaking:**` note; the intent of this spec is to avoid such
  changes.

#### NFR-HH-2 — Dependency directions preserved
*Traces to product NFR-6 and the structure steering doc.*

- After this spec is implemented, `uv run pytest tests/test_dependency_directions.py` SHALL pass,
  confirming no forbidden cross-package imports were introduced by the new modules.
- THE `vitals` package (including Component_Spec and `BloodPressure`) SHALL continue to import no
  other `vitals_on_fhir` package.

#### NFR-HH-3 — Interoperability
*Traces to product NFR-4.*

- THE Pipeline SHALL produce blood-pressure Observations conforming to FHIR R4 (4.0.1) and the US
  Core Blood Pressure profile, using LOINC and UCUM codings.
- THE Pipeline SHALL validate every generated resource with `fhir.resources` model validation before
  serving or storing it.
- THE domain model SHALL retain LOINC and UCUM bindings as class metadata independent of FHIR, so a
  future non-FHIR target mapper can consume the same `BloodPressure` objects without changes to the
  `vitals` package.

#### NFR-HH-4 — Provenance and licensing
*Traces to the security/provenance steering doc and product license rules.*

- Every source file added by this spec SHALL begin with `# SPDX-License-Identifier: AGPL-3.0-or-later`.
- Protocol knowledge for the BP_Profile SHALL be sourced only from published Bluetooth SIG, HL7/FHIR,
  or public vendor specifications, and cited in `docs/`; no code SHALL be copied, translated, or
  closely paraphrased from other projects or vendor SDKs.
- WHERE any third-party or EviTrace-ported material is included, THE Pipeline SHALL record it in
  `NOTICE` with the required fields.

#### NFR-HH-5 — Security and privacy unchanged
*Traces to product NFR-5 and the security steering doc.*

- THE new type, adapter, and mapper SHALL NOT introduce any non-FHIR side channel for measurement data.
- THE Pipeline SHALL NOT include measurement values in log messages at `INFO` level or above, and
  SHALL NOT include `VOF_API_TOKEN` in any log message at any level.
- THE CLI SHALL continue to bind to `127.0.0.1` by default; phase 2 SHALL NOT introduce remote
  deployment.

#### NFR-HH-6 — Test coverage
*Traces to product NFR-6 and the testing steering doc.*

- THE test suite SHALL include: an `__init_subclass__` metadata test for `BloodPressure`; BP_Parser
  tests covering well-formed mmHg and kPa payloads, the optional timestamp field, SFLOAT decoding,
  and malformed/short payloads; Component_Mapper tests asserting the US Core Blood Pressure
  Observation shape; validator tests for out-of-range systolic and diastolic; and BP_Adapter and
  BLE_Lifecycle behavior tests, including that a connected adapter emitting no Reading for an
  interval does not surface as a disconnection. The fast suite SHALL pass without hardware.
- THE existing heart-rate test suite (including the dependency-direction test) SHALL remain green
  after the BLE_Lifecycle extraction, serving as the regression guardrail.
- Hardware-dependent tests for real blood-pressure devices SHALL carry the `hardware` marker and be
  excluded from CI, consistent with the MVP convention.

---

## Out of scope

Per the product steering document and ADR-0001, this spec excludes:

- Oxygen saturation, body temperature, and body weight — deferred to sibling phase-2 specs.
- Mean arterial pressure as a blood-pressure component (may be added later, additively).
- Multiple simultaneous connected devices (still one device at a time).
- Persistence beyond in-memory storage (no database, disk, or remote store) — phase 4.
- Remote or cloud deployment and exposure to untrusted networks.
- SMART on FHIR authentication and outbound FHIR sinks — phase 4; not stubbed or referenced here.
- Phone health aggregators (Health Connect, HealthKit) — phase 3.
- Proprietary or reverse-engineered device protocols and any circumvention of device security.
- Writing to external EHRs or FHIR servers, and any write operation on the local API.
