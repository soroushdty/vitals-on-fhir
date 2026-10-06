<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Brief — session capture, review and export (a downstream consumer)

**Status:** Findings only. Not a decision. Input for ADR-0003.
**Date:** 2026-10-05. Prompted by a request for a record/stop/export interface for the mock
device, and by #10 item 1 (data volume and aggregation). The demo FHIR server needed for
server-side debugging is out of scope here and tracked in #19.

**Attribution.** Recommendations from published sources are quoted and attributed, or marked
*(paraphrased)*. How they apply to this codebase, and the proposals, are our own. Cite the
original sources, not this brief, in preprint text. Every FHIR shape proposed below was checked
with the HL7 FHIR validator (see [Validation method](#validation-method)).

## Decisions already taken by the project owner (2026-10-05)

These framed the investigation and are not reopened here.

1. **Capture first, curate later.** The whole session is captured from the moment a device
   connects, so nothing is lost if nobody pressed "record". The user can mark points of interest
   live. After stopping, the user reviews the session: picks the starting point, selects one or
   more crops (for example a pattern a physician wants to keep), and annotates them.
2. **Demo first, without authentication.** Annotations in demo mode are authored by a fixed user
   named `DEMO`.
3. **Persistence.** The in-memory-only rule applies to real data. Demo and debug data may be
   written to files. Real data may leave the process only through a proper, secure FHIR server
   connection (#9, roadmap phase 4). A demo FHIR server for simulating server scenarios is #19.
4. **The UI becomes a downstream consumer.** The core emits FHIR at the highest granularity it has
   (one Observation per reading). A consumer module, bundled and on by default, takes that output
   and owns sessions, crops, summaries and file export. Writing files becomes a function of the
   consumer, not the core.
5. **The feed uses FHIR Subscriptions** (the R4 backport).
6. **The consumer is a module inside the project, with a GUI and a TUI.** The GUI is the default;
   the TUI is chosen with `--tui` or a `default_ui` setting (`gui` | `tui`).
7. **Connection state must be expressed in FHIR**, not on a side channel. Investigated below.

## 1. Clinical precedent

Continuous capture with patient-marked events and later review is established practice in
ambulatory ECG monitoring. The 2017 ISHNE-HRS expert consensus statement [1]:

- Holter: "Patients may manually record in a diary or mark the occurrence of symptoms by pressing
  a built‐in switch on the recorder. AECG data are analyzed postrecording on a dedicated
  workstation."
- External loop recorders: "Upon event detection, ECG data are stored for a predefined amount of
  time prior to the event (looping memory) and a period of time after the activation."
- Syncope: "clinicians recommend outpatient cardiac telemetry with continuous recording
  independent of patient activation."

The design mirrors this: capture independent of activation, live marks, and review afterwards.
Unlike those devices, this project records heart *rate*, not an ECG, and is not a medical device.

## 2. What ties the dashboard to the core today

| Coupling | Where | In the new design |
|---|---|---|
| Non-FHIR `connection_state` message on the WebSocket | `dashboard/broadcaster.py` | A link-state Observation through the subscription (§4) |
| Non-FHIR `reset` message, and Simulate clearing the core's store | `cli.py` `_restart_hook` | A session boundary in the consumer (§9, question 3) |
| `/mock/scenarios`, `/mock/scenario` called by the page | `api/mock_control.py` | Unchanged: device control stays in the core |
| `/status` called by the page | `api/app.py` | Unchanged |
| Static files inside the core package, served by the core app | `api/app.py` `_mount_static` | Moved to the consumer module |
| Every Observation pushed to the page as a WebSocket message | `DashboardBroadcaster` | Replaced by the subscription feed |

`test_dependency_directions.py` already enforces package boundaries. A new `consumer` package
would be allowed to use only the core's published output (FHIR over the subscription and the
FHIR API) and the `fhir` constants, never `adapters`, `pipeline` or `store`.

## 3. The feed: FHIR Subscriptions, R4 backport

**Version.** The *Subscriptions R5 Backport* IG 1.1.0 (STU 1.1, 2023-01-11, trial use) is the
current published release; 1.2.0 is still a ballot [2]. For R4 the package is
`hl7.fhir.uv.subscriptions-backport.r4`. The base package id is R4B and produces version warnings
under R4.

**Topics in R4 are only canonical URLs.** "it was decided to leave topic definitions
out-of-scope in R4", and "FHIR R4 servers are not able to support custom topics submitted by
clients" [2, Components]. The topic URL goes in `Subscription.criteria`. The validator rejects
`example.org` URLs, so the topic needs a real project namespace.

**What a minimal conformant server must do** [2, Conformance; R4 server CapabilityStatement]:
- Support the Subscription resource (read is SHALL, create SHOULD) and the `$status` operation
  (SHALL). Support at least one channel type and one payload type.
- Reject a Subscription asking for an unsupported topic, channel or payload.
- Send notifications as a `history` Bundle whose first entry is the SubscriptionStatus
  `Parameters`, with `request`/`response` on every entry. Number events per subscription,
  monotonically; handshakes and heartbeats don't count.
- For `full-resource` payloads, reference each resource in `notification-event.focus` and include
  it in `entry.resource`.
- `$events` (replay a range of events) and `$get-ws-binding-token` (websocket channel) are MAY.

**Websocket channel.** The client gets a token from `$get-ws-binding-token`, opens the socket and
sends `bind-with-token`. The server then sends full notification Bundles (handshake, heartbeat,
event), and the client never acknowledges [2, Channels]. The IG gives no normative wire format
for the bind message, only a diagram ("bind-with-token token-abc"), so ours must be documented.
This is not the old R4 core websocket model, which only sent `ping` notices.

**No Python implementation exists.** We found no maintained server-side backport library.
`fhir-tbs` (MIT) is subscriber-side only. `fhir.resources`, already a dependency, can build
every resource needed. The server side is ours to write.

**Validation.** A backport Subscription, and handshake, heartbeat and event-notification Bundles
carrying a heart-rate Observation, validate with 0 errors against the `.r4` package. The one
warning, "ValueSet '…subscription-notification-type' not found", is an IG gap that also
appears with 1.2.0-ballot. Negative controls (status not first, wrong Bundle type, missing
payload content) correctly produce errors.

**What the IG does not cover.** Subscription `status` (`requested | active | error | off`) and
heartbeats describe the *channel*, not the device. Device connection state needs its own
resources (§4).

**Proposal.** One topic for vital-signs Observations and one for link-state Observations (§4),
both `full-resource`, over the websocket channel. The consumer subscribes over loopback even
though it runs in the same process, so it uses exactly the path an external subscriber would.
At 1 Hz the cost is negligible. Support `$events` too: the store already holds the Observations,
and it lets a consumer recover after reconnecting.

## 4. Connection state in FHIR

The adapter states are `DISCONNECTED`, `CONNECTING`, `CONNECTED` and `RECONNECTING`. "Off-wrist"
is not a state: it is a reading with `sensor_contact=False`, which the validator rejects today.

| Candidate | Evidence | Verdict |
|---|---|---|
| `Device.status` / `statusReason` | R4: Device is the "administrative" resource that "does not change much"; "DeviceComponent and DeviceMetric … model the physical part, including operation status and is much more volatile" [3]. R5: Device.status "is not the status of the device like availability" | The `statusReason` vocabulary fits (online, offline, not-ready…), the resource doesn't |
| `DeviceMetric.operationalStatus` | PHD IG 2.0.0 PhdDeviceMetric: "For a PHD device the operational status is only known when it is communicating. It is recommended to leave this field out." [4]. No code for reconnecting | Reject |
| PHD status Observations | PHD reports dynamic device state as Observations; its coincident-timestamp Observation has the PHD Device as `subject` and the gateway as `device` [4]. Sensor-status codes (MDC 150604, e.g. sensor-off) exist, but only for pulse oximeters. No MDC code for the device–gateway link | Use the pattern |
| `dataAbsentReason` on the vital | PHD measurement-status mapping: "Invalid → dataAbsentReason = DAR#error", "Not-available → … DAR#not-performed" [4]. US Core: `dataAbsentReason` is Must Support | Fits off-wrist and no-reading |
| AuditEvent, Communication | Security log, and clinician-to-recipient communication | Wrong semantics |

**Recommendation.**
- On each state change, emit a link-state **Observation**: `subject` = the device, `device` = a
  Device resource for the bridge itself (the gateway), `code` = a project code
  `connection-state`, and `valueCodeableConcept` = the THO `device-status-reason` code plus a
  project code holding the exact state. HTEST for simulated devices. `Device.status` stays
  `active`.
- Report off-wrist and missing readings as the vital-sign Observation with no value and a
  `dataAbsentReason`: `error` when the device flagged no skin contact, `not-performed` when no
  reading arrived. This is a core behaviour change (today these readings are dropped) and
  overlaps #7 (device-reported measurement status).

| State | `valueCodeableConcept` |
|---|---|
| CONNECTING | `device-status-reason#not-ready` + project `connecting` |
| CONNECTED | `device-status-reason#online` + project `connected` |
| RECONNECTING | `device-status-reason#offline` + project `reconnecting` |
| DISCONNECTED | `device-status-reason#offline` + project `disconnected` |
| Connected, off-wrist | (no link change) vital Observation with `dataAbsentReason` `error` |
| Connected, no reading | (no link change) vital Observation with `dataAbsentReason` `not-performed` |

R4 4.0.1 defines `online` as "The device is off.", a spec error that THO 3.0.0 corrects to "The
device is online."

**Trade-offs.** No published code exists for device link state, so a project CodeSystem is
needed; the validator warns until it is published. A link-state Observation has a Device as
subject, so a patient-scoped subscription filter doesn't match it; hence the separate topic. The
consumer derives the current state from the latest link-state Observation.

**Validation.** The plain link-state Observation, the vital Observation with `dataAbsentReason`
(`error` and `not-performed`), and the PHD-style devices all validate with 0 errors. The only
warnings are the unknown project CodeSystem and "observations should have a performer" (a
Device can't be an R4 performer).

## 5. Capture and memory

Measured with `tracemalloc` on 10,000 heart-rate readings (Python 3.12.13, project venv):

| Representation | Bytes per reading | 1 h at 1 Hz | 24 h | 7 days |
|---|---|---|---|---|
| R4B Observation object | 8,224 | 29.6 MB | 711 MB | 4.97 GB |
| Observation as a JSON string | ~1,500 | 5.4 MB | 130 MB | 910 MB |
| Two `array('d')` (time, value) | 16.2 | 0.06 MB | 1.4 MB | 9.8 MB |
| `array('d')` time + `array('f')` value | 12.2 | 0.04 MB | 1.1 MB | 7.4 MB |

The current store keeps 10,000 Observations, under three hours of heart rate. **Proposal:** the
consumer keeps each session as columnar arrays plus a short list of marks, crops and link-state
changes, and builds Observations only when exporting.

## 6. Review and export: FHIR shapes

Every shape below validated with 0 errors against US Core 9.0.0 and the PHD IG 2.0.0.

### Session summary (#10 item 1)

One Observation per window (one minute proposed): codes `8867-4` (required by the base heart-rate
profile) and `103205-1` "Mean heart rate", `effectivePeriod` = the window, `valueQuantity` = the
mean, and optional components `101692-2` "Maximum heart rate" and `103222-6` "Heart
rate.minimum".
- LOINC (2.82, via tx.fhir.org) has no per-minute mean, minimum or maximum; the hourly codes
  (`41920-0`, `8869-0`, `8879-9`) don't fit.
- The min/max components add four warnings: their codes are outside the vital-signs value sets.
- `8867-4` has time aspect "point in time" and `103205-1` "unspecified", so the two codings are
  not strictly equivalent.
- No R4 statistic extension exists. The `$stats` operation puts statistics in components the
  same way.
- **Rejected: one SampledData Observation per session.** The base R4 heart-rate profile allows
  only `valueQuantity`, so a SampledData Observation coded `8867-4` fails with 6 errors.

### Crop

A **`List`** (`mode=snapshot`) per crop: "A list is a curated collection of resources" [3].
It has `title`, `source` (the author), `note` (the annotation) and `entry.item` pointing at the
full-resolution heart-rate Observations, each a normal US Core Observation.
- List has no period element, so the time range comes from its entries and its title.
- Alternatives checked:
  - A grouping Observation with `hasMember` validates. With code `8867-4` it would appear in heart-rate searches with no value, and a project code adds nothing over List.
  - The PHD sample-array profile (`PhdRtsaObservation`) holds a crop compactly. It validates only with MDC codes instead of `8867-4`, IEEE 11073-style Device records and resampling to a fixed period. It's a later option.

### Point of interest

An Observation coded **`48767-8`** "Annotation comment [Interpretation] Narrative", with
`effectiveDateTime` = the marked time, `valueString` = the note, `performer` = the author, and
`focus`/`derivedFrom` = the nearest reading. It works whether or not the point falls inside a
crop. `List.entry.date` doesn't work: it means "when item added to list", and in a snapshot List
it breaks rule lst-3.

### Author

`Practitioner/demo` named `DEMO`, labelled HTEST, referenced from the List `source`, the note
`authorReference` and the point-of-interest `performer`. Also valid as US Core Practitioner if
given an identifier and `name.family`. With authentication (#9), the real user replaces it and
the shape stays the same.

### Export Bundle

A **`collection`** Bundle for files ("imposes no processing obligations or behavioral rules
beyond persistence") containing the Patient, Device(s), `Practitioner/demo`, the summaries, the
raw Observations inside crops, the Lists and the points of interest, linked by `urn:uuid`
references.
- A validated sample has 0 errors.
- A `transaction` version (entries with `PUT`) also validates. It is what #19's demo server
  would receive.
- A `document` Bundle needs a Composition and implies attestation, which is too heavy here.

### File rule

The consumer writes a resource to a file only if it carries the `HTEST` security label (ADR-0002,
PR #18). Real data therefore can't reach disk even through a UI bug.

## 7. UI technology

**GUI.** Vendor **uPlot**: MIT, about 22 KB gzipped (51 KB minified), canvas-based. It supports
range selection without zooming through `cursor.drag.setScale: false` and the `setSelect` hook.
Its README: "No built-in drag scrolling/panning". The server sends downsampled windows at about
twice the pixel width:
- min/max per bucket keeps spikes exactly, which matters for review. It took 4.0 ms for 86,400
  points into 1,000 buckets, in pure Python.
- LTTB [5] looks smoother (6.6 ms).

The current hand-drawn SVG remains fine for the two-minute live view.

**TUI.** **Textual** (MIT; 8.2.8, 2026-06-30). `run_async` runs on the caller's event loop, so it
shares the loop with uvicorn and the pipeline, and `run_test` gives headless tests. Charts need
a custom widget, or `textual-plot` (MIT; zoom and pan; needs numpy). `textual-plotext` is stale
and capped below the current plotext. urwid (LGPL-2.1) and prompt_toolkit (BSD) would need much
more widget work. All of these licences are compatible with AGPL-3.0.

**One process, verified.** A proof of concept ran Textual, uvicorn and a fake acquisition task on
one loop, under a pseudo-terminal and headless.
- **Problem:** uvicorn's default logging wrote raw lines into the TUI's screen.
- **Fix, verified with zero leaked lines:** pass `log_config=None`, route uvicorn's loggers to the
  root logger, and attach a file handler plus a handler that writes to a Textual log panel.
- **Ctrl+C:** in a TUI it arrives as a key press, so the quit action must set
  `server.should_exit = True` itself.

**Selecting the UI.** A `default_ui` setting (`gui` | `tui`) with `--tui` overriding it, following
the existing precedence (CLI > environment > `.env` > `config.yaml` > default).

## 8. Scope and governance

The design conflicts with current steering text. ADR-0003 has to amend it explicitly.

1. **`product.md`, Mission:** "Downstream applications, analytics, and clinical decision support
   are permanently out of scope. The MVP web dashboard is a demonstration consumer of the FHIR
   API, not the product itself." A possible reading: the consumer stays a *reference* consumer of
   the bridge's own output. Human annotation and descriptive summaries (mean, minimum, maximum)
   are not decision support. No automatic detection or alerting is added.
2. **`product.md`, deferred items:** "Persistence beyond in-memory storage — phase 4". Per
   decision 3, this would apply to real data only, and HTEST-labelled data may be written to
   files.
3. **Phase.** Phase 2 (home health devices) is the only open phase. This work cuts across phases.
   The ADR should say whether it amends the current scope or opens something new.
4. **Requirements.** Reporting off-wrist and missing readings as `dataAbsentReason` Observations
   changes how rejected readings are handled today. The Subscriptions feed and the consumer need
   new requirement IDs.
5. **Not a medical device.** The review UI should carry the same disclaimer as the dashboard.

## 9. Questions for ADR-0003

1. The wording of the `product.md` amendments in §8.
2. How the consumer reaches the core: websocket over loopback (proposed) or a custom in-process
   channel.
3. Session boundaries: a new device connection starts a new session. Should Simulate behave like
   a reconnect, giving a natural boundary, instead of clearing the core's store?
4. Summary window length (one minute proposed), and mean only or mean + min + max.
5. Crops as `List` now, with the PHD sample array as a later option.
6. Where exports go: a server folder, a download, or both (deferred by the owner).
7. Whether the #10 summaries also apply outside exports, to the live API and the phase-4
   outbound sink (deferred by the owner).
8. Accepting the core behaviour change for off-wrist and missing readings (§4).
9. The canonical namespace for the project's CodeSystems and topics, and whether the core serves
   them so validators can resolve them.
10. TUI charts: a custom widget, or `textual-plot` with numpy as a new dependency.

## 10. Staged plan (to become issues once ADR-0003 is accepted)

**Prerequisites:**
- Merge PR #18 (the `HTEST` label).
- Fix #10 item 4 (Device identifier systems), because the mock Device fails validation today.
- Fix #17 (SpO2 coding).

1. **Core feed.** Backport Subscriptions server (topics, websocket channel, `$status`, `$events`),
   link-state Observations and a bridge Device. The old WebSocket messages stay until stage 3.
2. **Consumer skeleton.** The `consumer` package and its dependency rule, columnar session
   capture, per-window summaries, and the `default_ui` / `--tui` selection.
3. **GUI.** Move the live view into the consumer and add live Mark. Then review (start point,
   crops, annotations) with uPlot, and file export under the HTEST rule. Then remove the old
   messages.
4. **TUI.** Live view, Mark, review and export in Textual.
5. **Later.**
   - `transaction` export to the demo server (#19).
   - Real data through a secure outbound connection (phase 4, #9).
   - Compact crops with the PHD sample array.

## Validation method

HL7 FHIR validator 6.10.4, `-version 4.0.1 -ig hl7.fhir.us.core#9.0.0 -ig hl7.fhir.uv.phd#2.0.0`
(plus `-ig hl7.fhir.uv.subscriptions-backport.r4#1.1.0` for §3), run 2026-10-05. Every resource
also gets the narrative warning dom-6, which is not repeated above. Shapes that differ from the
current output were built by hand from the shapes the mappers produce, then validated one at a
time and inside Bundles.

## References

1. Steinberg JS, Varma N, Cygankiewicz I, et al. 2017 ISHNE-HRS expert consensus statement on
   ambulatory ECG and external cardiac monitoring/telemetry. *Heart Rhythm*. 2017;14(7):e55–e96.
   PMID [28495301](https://pubmed.ncbi.nlm.nih.gov/28495301/);
   doi:[10.1016/j.hrthm.2017.03.038](https://doi.org/10.1016/j.hrthm.2017.03.038). Also in
   *Ann Noninvasive Electrocardiol*. 2017;22(3):e12447, PMCID
   [PMC6931745](https://pmc.ncbi.nlm.nih.gov/articles/PMC6931745/).
2. HL7 International. *Subscriptions R5 Backport* IG 1.1.0 (STU 1.1), 2023-01-11. Pages
   Components, Conformance, Channels, Notifications, Payloads, Errors.
   <https://hl7.org/fhir/uv/subscriptions-backport/STU1.1/>
3. HL7 International. *FHIR R4* 4.0.1: Device, DeviceMetric, Observation, List, Bundle.
   <https://hl7.org/fhir/R4/>
4. HL7 International. *Personal Health Device FHIR IG* 2.0.0 (STU2), 2026-04-01:
   PhdBaseObservation, PhdDeviceMetric, PhdCoincidentTimeStampObservation, PhdRtsaObservation,
   ProfileConsumers. <https://hl7.org/fhir/uv/phd/>
5. Steinarsson S. *Downsampling Time Series for Visual Representation.* MSc thesis, University of
   Iceland, 2013. <http://hdl.handle.net/1946/15343>
6. HL7 International. *US Core Implementation Guide* 9.0.0 (STU9). <https://hl7.org/fhir/us/core/>
7. HL7 Terminology (THO): `device-status-reason`, `data-absent-reason`, `v3-ActReason`.
   <https://terminology.hl7.org/>
8. LOINC 2.82, looked up through <https://tx.fhir.org/r4>: 8867-4, 103205-1, 101692-2, 103222-6,
   41920-0, 8869-0, 8879-9, 48767-8.
9. uPlot, <https://github.com/leeoniya/uPlot> (MIT). Textual, <https://textual.textualize.io/>
   (MIT).
