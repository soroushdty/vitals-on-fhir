<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Brief — per-vital validation modes (plausibility vs personal/clinical relevance)

**Status:** Idea only. Not scheduled, not a decision. Recorded so it need not be re-derived.
**Not part of** any current spec. Built no code and changed no behavior when written — this brief was
authored during the `body-temperature` slice because the temperature-bounds discussion surfaced the
distinction below, but it captures an idea for a possible future spec, nothing more.

## The distinction that prompted this

Setting the body-temperature plausible range to a deliberately wide `(10.0, 47.0)` °C made explicit a
distinction the project had not written down: there are **two different kinds of "is this value
acceptable?" check**, and they must not be conflated.

- **Physical plausibility** is a device/physics-bound accept-or-reject decision: *could a live human
  body have produced this value at all?* This is exactly what the current `PlausibleRangeValidator`
  does. Its job is to reject artifacts — decode errors, a malfunctioning sensor, an ambient or
  wrong-sensor reading — not to judge health. The temperature bounds encode this: wide enough to admit
  every temperature a human body has been documented to reach and survive, narrow enough to reject the
  clearly non-physiological.
- **Personal/clinical relevance** is a person-bound judgment: *is this value normal, high, or low for
  this person?* That is a different kind of check entirely, and one only the user or their clinician
  can supply. A plausibility validator has no business making it.

## Decision (user-approved): flag, never drop

If personal or clinical thresholds are ever added, they must **annotate/flag** a reading — for
example by setting FHIR `interpretation` (normal / high / low) on the Observation — and must
**never drop** it.

Dropping a genuine abnormal reading would violate the project's faithful-representation mission: an
abnormal-but-real temperature is precisely the reading a caregiver most needs to see. Only
physical-plausibility violations — which are almost certainly artifacts — are dropped. Everything a
real body can produce is represented, and any personal/clinical judgment rides *on top* as an
annotation, not as a gate.

## Three options for deriving personal thresholds (honest tradeoffs)

1. **Predefined keyword modes** — e.g. a "full-range" mode versus a "conventional/clinical" mode
   selected by name.
   *Tradeoff:* needs curated, cited per-vital reference data. That sits in tension with the product's
   explicit "not a clinical-reference tool" scope, so the curation burden and the scope question would
   both have to be resolved first.

2. **±k·SD with a user-selectable k (default k = 2).**
   *Tradeoff:* needs either a population mean/SD or a per-person rolling baseline, which in turn needs
   stored measurement history (dependent on phase-4 persistence). More importantly, at k = 2 this band
   excludes roughly 5% of genuine readings, so it is **only defensible as a flagging heuristic, never
   as a drop rule** — using it to reject readings would discard about one in twenty real measurements.

3. **Explicit per-person bounds** supplied directly by the user or clinician.
   *Tradeoff:* the simplest and most honest, but puts the burden on the user to provide the numbers;
   no automatic derivation.

## Dependencies and guardrails if this is ever picked up

- It rides on **structured configuration** — the optional `config.yaml` idea in
  `docs/brief-config-file.md`. Modes, k-factors, and per-person option sets do not express cleanly as
  flat `VOF_<VITAL>_<BOUND>` env pairs.
- It likely needs **stored per-person history** (phase 4 persistence), at least for options that
  derive a baseline.
- It would be **its own spec** with its own requirements and a `CHANGELOG.md` entry — not folded into
  a vital-sign slice.
- Regardless of which option is ever pursued, the **physical-plausibility bounds stay wide and
  physics-based**. Personal thresholds layer on top of plausibility as a flagging concern; they never
  replace or narrow the drop bounds.
