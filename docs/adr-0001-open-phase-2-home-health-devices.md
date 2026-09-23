<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# ADR-0001 — Open roadmap phase 2 (home health devices)

- **Status:** Accepted
- **Date:** 2026-09
- **Deciders:** Soroush Dianaty, Nusrat Ashrafi, Isha Uttham
- **Context tags:** scope, roadmap, object-model

## Context

The heart-rate MVP (roadmap phase 1) is complete and verified. All functional
requirements FR-1 through FR-13 and non-functional requirements NFR-1 through
NFR-6 are implemented in `src/vitals_on_fhir/`, and the three CI gates pass:

- `ruff check .` — clean
- `mypy src` — no issues (strict mode, 34 source files)
- `uv run pytest` — 74 passed, 5 deselected (the `hardware`-marked tests, which
  require a physical device and are excluded from CI by design)

Completing the MVP does not automatically move the project to the next roadmap
item. The roadmap in `docs/roadmap.md` and `product.md` is explicitly
context-only ("do not plan work for these"). Promoting a roadmap phase to active
work is a deliberate scope decision, recorded here so the change is traceable for
the planned preprint.

The candidate phases were:

2. Home health devices via standard Bluetooth health profiles (BP, SpO2,
   temperature, weight).
3. Phone health aggregators (Android Health Connect, Apple HealthKit).
4. Persistence and outbound integration (durable stores, outbound FHIR sinks,
   SMART on FHIR auth, adapter entry-point discovery).
5. Additional concrete adapters as separately licensed packages.

## Decision

**We open roadmap phase 2: home health devices via standard Bluetooth health
profiles.** All other phases remain closed and context-only.

Phase 2 is scoped in this project to introduce, without breaking changes to the
object model:

- New vital-sign types under `vitals/builtin/`, including the **first concrete
  `ComponentVital` (blood pressure)** alongside new `ScalarVital` types (pulse
  oximetry / oxygen saturation, body temperature, body weight).
- Generalized BLE acquisition beyond the Heart Rate Service, with **per-profile
  payload parsers** for the standard Bluetooth health profiles.
- **Store-and-forward** support: readings whose `effective` (measurement) time
  differs from their `issued` (processing) time.
- The activation of `ComponentVitalMapper`, currently a documented roadmap stub.

### Delivery: one sibling spec per profile

Phase 2 is delivered as a series of sibling specs rather than one large change, so
each is reviewable and landable independently:

- **`home-health-devices` (first, this spec): blood pressure only.** It introduces
  the first concrete `ComponentVital`, defines the concrete `ComponentVital` shape,
  extracts the reusable BLE lifecycle, and adds store-and-forward. Blood pressure is
  first because it activates the `ComponentVital` / `ComponentVitalMapper` half of
  the object model and forces the component-model design decisions.
- **Later sibling specs:** oxygen saturation (pulse oximetry — most complex, SFLOAT,
  spot-check vs continuous), body temperature, and body weight, each as its own spec.

### Resolved design decisions (requirements review)

- **Component model (Option A).** `ComponentVital` declares its component structure
  as typed class metadata (per-component `loinc_code`, `ucum_unit`, field name) and
  carries values as named typed instance fields (`systolic`, `diastolic`). This
  mirrors `ScalarVital`, keeps the `vitals` layer FHIR-free, and keeps LOINC/UCUM
  semantics in the target-neutral domain model so a future non-FHIR mapper (e.g.
  OMOP/openEHR) is a thin loop, not a rewrite. Analytics targets remain out of scope;
  this is design-for-optionality at no extra cost, not planned work.
- **Mean arterial pressure omitted.** MAP is device-derived, not independently
  measured; `BloodPressure` models systolic + diastolic. MAP can be added later as an
  additive component with no ABC change.
- **Generalized BLE via composition.** The profile-agnostic BLE lifecycle is factored
  into a reusable unit that concrete adapters use by composition, not a new
  inheritance level, respecting the 3-level inheritance cap. The extraction preserves
  the public surface of `BleHeartRateAdapter`.

## Rationale

- **Cohesion with proven architecture.** Phase 2 reuses the exact extension
  points the MVP validated: new `DeviceAdapter` / parser subclasses, new
  `VitalSign` subclasses, new validators. It stays within the project's "bridge"
  mission (acquire via open standards, expose as FHIR) and adds no new
  deployment shape.
- **First real exercise of the whole object model.** Blood pressure activates
  the `ComponentVital` / `ComponentVitalMapper` half of the hierarchy that the
  MVP never used, surfacing any design gaps while the model is still young.
- **Phase 4 is deliberately deferred.** SMART on FHIR and durable persistence
  are coupled to remote, multi-user, consent-based access — a deployment shape
  the project does not yet have (it binds to `127.0.0.1`, single-user,
  in-memory). Building that auth now would wire a large subsystem into nothing.
  When phase 4 is opened, those items should be taken on together.

## Consequences

- The `home-health-devices` spec carries the first phase-2 slice (blood pressure);
  oxygen saturation, temperature, and weight follow as sibling specs. New FR-/NFR- IDs
  introduced there are additive; existing MVP IDs are not renumbered (preprint
  traceability).
- New protocol knowledge (Bluetooth SIG health-profile characteristic formats)
  must be cited in `docs/`, sourced only from published specifications, per the
  provenance rules.
- The permanent out-of-scope list in `product.md` still applies: no multiple
  simultaneous devices, no persistence beyond in-memory, no remote deployment,
  no proprietary/reverse-engineered protocols. Phase 2 widens the set of
  *vital-sign types and standard profiles*, not those boundaries.
- `product.md` (MVP scope / roadmap) should be updated in a follow-up to reflect
  that phase 2 is active, keeping the steering docs and this ADR consistent.
