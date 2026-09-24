<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Brief — alignment with PGHD/EHR-integration guidance and SMART on FHIR

**Status:** Findings only. Not scheduled, not a decision. Recorded so it need not be re-derived.
**Not part of** any current spec. This brief records a 2026-09-23 review of the repository against two
published papers, one HL7 implementation guide, and the SMART App Launch specification. It
built no code and changed no behavior. The concrete work items are tracked as GitHub issues #6–#11.
The SMART recommendation below is input for the ADR that opens roadmap phase 3. It is not itself a
decision.

**Attribution.** The recommendations summarized here belong to the authors of the sources listed in
[References](#references). How they apply to this codebase, and the proposed responses, are our own.
Wording from a source is either quoted and attributed or marked *(paraphrased)*. Cite the original
sources, not this brief, in any preprint text that builds on it.

## Sources reviewed

1. **Dinh-Le et al. (2019) [1]**: a scoping review of how wearable data is being integrated into EHRs,
   focused on Epic. It is a survey of the field, not a standard. Its main contribution is three
   barriers: patient privacy, lack of system interoperability, and data overload *(paraphrased)*.
2. **Nichols et al., IFCC C-MHBLM (2024) [2]**: consensus best-practice recommendations for bringing
   patient-generated data from mobile devices into EHRs. They cover where the data is stored and
   displayed, privacy, data security, quality assurance, alert triggers, staff training, and
   collaboration with industry.
3. **HL7 Personal Health Records IG, PGHD page [3]**: marked *Informative*, and a continuous-integration
   build of `1.0.0-ballot2`, not an authorized publication. It has no conformance rules to test
   against. Always cite the version and build date, because the content changes.
4. **SMART App Launch STU 2.2 [4]**: the current published version, trial use, FHIR R4. Pages read:
   the overview, Conformance, and Best Practices in full; Backend Services up to the token request;
   and the normative statements of App Launch.

## Findings

### Already aligned

- **Open standards throughout**, which answers the interoperability barrier in [1]: FHIR R4, US Core
  vital-signs profiles, LOINC, UCUM, and standard Bluetooth SIG health profiles only.
- **Consistent format across devices** [2]: mapping is driven by class metadata, so every device
  produces the same Observation shape. BP in kPa is normalized to mmHg.
- **Vital-sign placement** [2]: every Observation, including SpO2, uses `category: vital-signs`, never
  `laboratory`. [2] asks that mobile-device data stay out of the laboratory section of the record
  *(paraphrased)*.
- **Data fidelity** [2]: malformed payloads are dropped, resources are validated when they are built,
  and duplicate readings are rejected.
- **PGHD data structure** [3]: the guide maps the type / value+unit / metadata split onto
  `Observation.code`, `valueQuantity` or `component`, and `effectiveDateTime` or `device`. That is the
  same shape this repository emits. Where [3]'s code-mapping table gives a LOINC code, the repository
  uses the same one: 8867-4, 8310-5, 29463-7, 8480-6, 8462-4.
- **Honest disclosure** [1][2]: not HIPAA-compliant, the unauthenticated BLE channel, and
  localhost-only operation are all stated in the README and on the dashboard.

### Gaps (tracked as issues)

| Issue | Gap | Source |
|---|---|---|
| #6 | Device-sourced Observations look the same as clinician-recorded vitals. The only sign of their origin is `Observation.device`, and mock data is not marked as simulated. [2]: "It is essential to distinguish vital signs recorded by healthcare professionals from data received from a personal mobile health device." Our own `fhir-conventions.md` ("Do not add extra fields…") currently blocks the fix. | [2]; [3] partial |
| #7 | The BP Measurement Status and PLX Measurement / Device-and-Sensor Status fields are only counted for payload length. Readings the device itself flags as unreliable are still published as `final`. | [2] (quality assurance) |
| #8 | The device user ID on multi-user BP cuffs and scales is never decoded, so every reading is attributed to the single `VOF_PATIENT_ID`. This is a wrong-patient risk. | [2] |
| #9 | No TLS, audit log, encryption at rest, or scoped access control. Acceptable for localhost; a hard prerequisite before any remote access. | [1], [2] |
| #10 | Minor items: no heart-rate aggregation for the EHR (with `valueSampledData` as an option [3]); no rejection counters; no device-validation evidence; `Device.identifier.system` values are not URIs; alerts and staff training recorded as deliberate non-goals (`product.md`). | [1], [2], [3] |
| #11 | The thermometer's Temperature Type (measurement site) field is not decoded, so `Observation.bodySite` is never set. [3] maps measurement context to `bodySite` and `method` *(paraphrased)*. | [3] |

### Upstream observation

In the reviewed build of [3], the *PHR Code Mapping* table leaves the LOINC cell empty for the
`bloodPressure` panel and `oxygenSaturation` rows. This repository uses 85354-9 and 59408-5, which the
US Core profiles require. The table appears incomplete, and our codes are not wrong. If a later build
still has the gap, report it through the IG's "Propose a change" link. The same table maps HealthKit
and Health Connect identifiers to LOINC, which is directly useful for roadmap phase 3.

## SMART on FHIR and roadmap placement

SMART plays three distinct roles for this project. They belong in different phases.

| Role | SMART pattern [4] | Placement |
|---|---|---|
| **A. Clients reading or writing the bridge's API** (bridge as resource server) | App Launch and scopes. Servers requiring authorization SHALL serve `/.well-known/smart-configuration`, SHALL support PKCE `S256` (and SHALL NOT support `plain`), and the resource server SHALL validate token expiry and scope. | **Phase 3**, in minimal form (below) |
| **B. Bridge pushing to an external EHR** (bridge as client) | Backend Services: the `client_credentials` grant with asymmetric JWT client authentication, TLS 1.2 or later, and the client's public key registered in advance. | Phase 4, together with the outbound `ObservationSink` |
| **C. Reading HealthKit / Health Connect** | Not SMART. These are OS-level permission APIs. | n/a |

**Why part of SMART moves to phase 3.** HealthKit is available only on iOS and Health Connect only on
Android, so a desktop Python process can't read either directly. A phase-3 aggregator adapter will
most likely need a companion phone app that sends readings to the bridge over the network. This is an
inference to confirm in the phase-3 design, not a settled fact. That network hop is the first time a
remote client talks to the bridge. It removes the premise behind ADR-0001's deferral ("Building that
auth now would wire a large subsystem into nothing"): a shared static token over plain HTTP from a
phone is exactly what SMART and TLS exist to replace.

**Recommended scope for the phase-3 ADR:**

1. **Resource server only.** Do not build an authorization server. Delegate to an existing one, such as
   Keycloak. The bridge validates tokens (JWT verification, or the token introspection that [4]
   defines for loose coupling) and serves `/.well-known/smart-configuration` pointing to that
   authorization server.
2. **SMART v2 granular scopes.** [4]'s own example limits `patient/Observation.rs` with a
   `?category=` suffix, which fits a vital-signs-only API. The phone app gets write access to
   vital-sign Observations; read-only consumers get read access.
3. **Target capability set:** "Patient Access for Standalone Apps" (`launch-standalone`, a client
   type, `context-standalone-patient`, `permission-patient`), which matches UC-1.
4. **TLS in the same phase.** [4] requires TLS for all token exchanges, so the transport part of #9
   becomes a phase-3 entry criterion.
5. **Keep `StaticTokenAuthenticator`** for local and mock use.

**Prerequisite regardless of phase.** `Authenticator.authenticate(credentials) -> bool`
(`src/vitals_on_fhir/api/auth.py`) can't express scopes or patient context. It has to return an
authenticated principal with granted scopes before any SMART implementation can plug in without
reworking the ABC. That is a public-ABC change, and it needs a `CHANGELOG.md` entry.

**Governance changes this implies:**

- A new ADR that opens phase 3 with the minimal role A in scope. It supersedes ADR-0001's "Phase 4 is
  deliberately deferred" rationale for this item only; durable persistence stays in phase 4.
- An amendment to `.kiro/steering/security-privacy.md`, which currently says "SMART on FHIR is a
  roadmap item; do not stub or reference it in the MVP code".
- Updates to phases 3 and 4 in `docs/roadmap.md` and `.kiro/steering/product.md`, and re-scoping #9 so
  TLS and SMART role A become phase-3 entry criteria.

## Open questions

- Does the phase-3 adapter really need a phone-to-bridge network hop, or could it be designed without
  one (for example, file export or on-device execution)? If there is no hop, the case for bringing
  SMART into phase 3 is weak.
- Which provenance representation should #6 use (`performer`, `meta.tag`, `Provenance`, or the PGHD
  code system in [3] once it is published)? This should be decided in the same ADR round, because it
  also changes `fhir-conventions.md`.

## References

1. Dinh-Le C, Chuang R, Chokshi S, Mann D. Wearable Health Technology and Electronic Health Record
   Integration: Scoping Review and Future Directions. *JMIR mHealth and uHealth*. 2019;7(9):e12861.
   doi:[10.2196/12861](https://doi.org/10.2196/12861). PMID
   [31512582](https://pubmed.ncbi.nlm.nih.gov/31512582/); PMCID
   [PMC6746089](https://pmc.ncbi.nlm.nih.gov/articles/PMC6746089/).
2. Nichols JH, Assad RS, Becker J, Dabla PK, Gammie A, Gouget B, Heydlauf M, Homsak E, Korita I,
   Kotani K, Saatçi E, Stankovic S, Uygun ZO, AbdelWareth L. Integrating Patient-Generated Health Data
   from Mobile Devices into Electronic Health Records: Best Practice Recommendations by the IFCC
   Committee on Mobile Health and Bioengineering in Laboratory Medicine (C-MHBLM). *EJIFCC*.
   2024;35(4):324–328. PMID [39810897](https://pubmed.ncbi.nlm.nih.gov/39810897/); PMCID
   [PMC11726333](https://pmc.ncbi.nlm.nih.gov/articles/PMC11726333/).
3. HL7 International / Patient Empowerment Work Group. *Personal Health Records Implementation Guide*
   (`hl7.fhir.uv.phr`), version 1.0.0-ballot2, continuous build generated 2026-09-17. Pages "Patient
   Generated Health Data (PGHD)" (Informative) and "PHR Code Mapping".
   <https://build.fhir.org/ig/HL7/personal-health-record-format-ig/en/pghd.html>
4. HL7 International. *SMART App Launch Implementation Guide*, version 2.2.0 (STU 2.2), 2024-04-30,
   FHIR R4. <https://hl7.org/fhir/smart-app-launch/STU2.2/>

Bibliographic metadata for [1] and [2] was retrieved from PubMed (NCBI/NLM). PubMed returned no DOI
for [2].
