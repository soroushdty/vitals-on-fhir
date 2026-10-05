<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# ADR-0002 — Mark Observations as patient-generated, and simulated data as test data

- **Status:** Accepted
- **Date:** 2026-10
- **Deciders:** Soroush Dianaty
- **Context tags:** fhir, provenance, interoperability
- **Issue:** #6

## Context

Every Observation this project builds comes from a consumer device the patient
uses at home. Before this decision, the only sign of that was `Observation.device`.
An EHR receiving the data in roadmap phase 4 could not tell it apart from vital
signs a clinician recorded. The IFCC C-MHBLM recommendations [1] state: "It is
essential to distinguish vital signs recorded by healthcare professionals from data
received from a personal mobile health device." Dinh-Le et al. [2] observe that
patient-collected data loses value when it cannot be integrated cleanly with the
patient's historical record *(paraphrased)*.

Two further problems:

- Readings from the mock adapters produced FHIR output that looked exactly like
  real measurements.
- `.kiro/steering/fhir-conventions.md` forbade any field "unless a US Core profile
  explicitly requires them", so no marker could be added.

### Sources reviewed (2026-10-05)

- **US Core 9.0.0** (STU9, 2026-05-31, the current release) [3]. In the vital-signs
  profiles `Observation.performer` is 0..\* and Must Support, and its allowed
  targets include US Core Patient. The profile page: "The profile elements
  Observation.performer and Observation.device communicate the individual level
  provenance author data corresponding to the U.S. Core Data for Interoperability
  (USCDI) Provenance Author Data Elements." Its *Writing Vital Signs* page [4] is
  informative: "they carry no US Core conformance or certification requirements
  until the page standards status changes from 'informative'". It says patient-facing
  apps "SHALL set the performer to a reference to the patient" when the patient
  collected the data. It also proposes a `meta.tag` `patient-supplied` from the
  `us-core-tags` code system, and `PATAST` in `meta.security` as an alternative
  ("We are seeking feedback").
- **HL7 Personal Health Device (PHD) IG 2.0.0** (STU2, 2026-04-01) [5]. Its
  `PhdBaseObservation` requires a category coding
  `http://hl7.org/fhir/uv/phd/CodeSystem/PhdObservationCategories#phd`, defined
  as "An observation coming from a personal health device, either directly or via
  a personal health gateway that maps the data received from the PHD into a FHIR
  Observation resource." It marks test or demo data with `meta.security`
  `HTEST`. It leaves `performer` unconstrained.
- **HL7 Personal Health Records IG**, PGHD page [6]. Still the 1.0.0-ballot2 CI
  build generated 2026-09-17, with no published release. It prescribes no marker
  (see the comment on #6).
- **FHIR R4 security labels** [7]: "Test Data: … This marks that a resource has
  been created to test an application, and is not real production data". The code
  is `HTEST` ("test health data") in
  `http://terminology.hl7.org/CodeSystem/v3-ActReason`. The R4 page links it to
  ActCode, but the code is defined in ActReason, which the PHD IG also uses.
- **FHIR R4 Meta**: "Applications are not required to consider the tags when
  interpreting the meaning of a resource." Security labels, by contrast, may change
  access rules.

### Validation evidence

Candidate markers were added to one Observation per vital type from the mock
adapters, then checked with the HL7 FHIR validator 6.10.4
(`-version 4.0.1 -ig hl7.fhir.us.core#9.0.0`, plus `-ig hl7.fhir.uv.phd#2.0.0`
for the final output):

| Candidate | Result |
|---|---|
| `performer` = Patient | No new issues; clears the "all observations should have a performer" warning |
| Extra category `phd` | No new issues (the code is found once the PHD IG is loaded) |
| `meta.security` `HTEST` | No new issues, on Observations and Devices |
| `meta.security` `PATAST` | No new issues |
| `meta.tag` `patient-supplied` | **Two errors per Observation**: the published `us-core-tags` CodeSystem (5.0.1, complete) defines only `sdoh` |

The same run found two existing problems that this decision does not change: SpO2
Observations lack the second required LOINC code `2708-6` (#17), and the mock
Devices' identifier system `mock` is not an absolute URI (#10).

## Decision

1. **`Observation.performer` = `Reference(Patient/<VOF_PATIENT_ID>)`** on every
   Observation. The patient collects the reading themselves; this is the US Core
   provenance-author element.
2. **A second `category` coding, PHD `phd`**, next to `vital-signs`, on every
   Observation. Its published definition describes exactly what this bridge does:
   a personal health gateway mapping device data to FHIR.
3. **`meta.security` `HTEST`** on every Observation from a simulated device, and on
   the simulated Device itself. Mock output can then never be taken for a real
   measurement, and a receiving system may apply different access rules to it.
4. **No `Provenance` resource yet.** The read-only, in-memory API has nowhere to
   serve one. US Core's writing page describes `Provenance` (author, transmitter)
   for writing data to a server, which belongs with the phase-4 outbound sink.
5. **Not the `patient-supplied` tag**, because it fails validation against the
   published code system. **Not `PATAST`**: "asserted by a patient" fits data a
   patient types in better than a device measurement, and the `phd` category
   already says where the data came from. Revisit both if the US Core writing page
   becomes normative.

## Implementation

- `ScalarVitalMapper` and `ComponentVitalMapper` set `performer` and add the `phd`
  category (`fhir/provenance.py`: `PHD_CATEGORY`).
- `DeviceInfo.simulated` (default `False`); the five mock adapters set it.
  `build_device` labels a simulated Device with `HTEST`.
- The orchestrator applies `mark_simulated` to every Observation from a simulated
  device, whichever mapper built it, so the `VitalMapper` interface is unchanged
  and a third-party mapper cannot drop the label.
- `fhir-conventions.md` now lists these fields in the canonical Observation shape
  and allows fields that a published HL7 IG or a US Core Must Support element calls
  for, when an ADR records the choice.

## Consequences

- Receivers can tell device data from clinician data by `category`, and see who
  collected it in `performer`, without reading `device`.
- Mock data is labelled in the FHIR API, the dashboard feed, and any future
  outbound sink.
- `DeviceInfo` gains a field with a default, so existing adapters keep working. A
  third-party simulated adapter must set `simulated=True` to be labelled.
- On multi-user devices, `performer` inherits the same attribution risk as
  `subject` (#8). It is not a new risk.
- Phase 4 should revisit `Provenance` for outbound writes, and the US Core writing
  page's status.

## References

1. Nichols JH, Assad RS, Becker J, Dabla PK, Gammie A, Gouget B, Heydlauf M,
   Homsak E, Korita I, Kotani K, Saatçi E, Stankovic S, Uygun ZO, AbdelWareth L.
   Integrating Patient-Generated Health Data from Mobile Devices into Electronic
   Health Records: Best Practice Recommendations by the IFCC Committee on Mobile
   Health and Bioengineering in Laboratory Medicine (C-MHBLM). *EJIFCC*.
   2024;35(4):324–328. PMID [39810897](https://pubmed.ncbi.nlm.nih.gov/39810897/);
   PMCID [PMC11726333](https://pmc.ncbi.nlm.nih.gov/articles/PMC11726333/).
2. Dinh-Le C, Chuang R, Chokshi S, Mann D. Wearable Health Technology and
   Electronic Health Record Integration: Scoping Review and Future Directions.
   *JMIR mHealth and uHealth*. 2019;7(9):e12861.
   doi:[10.2196/12861](https://doi.org/10.2196/12861). PMID
   [31512582](https://pubmed.ncbi.nlm.nih.gov/31512582/); PMCID
   [PMC6746089](https://pmc.ncbi.nlm.nih.gov/articles/PMC6746089/).
3. HL7 International. *US Core Implementation Guide* 9.0.0 (STU9), 2026-05-31.
   Profiles `us-core-vital-signs`, `us-core-heart-rate`.
   <https://hl7.org/fhir/us/core/>
4. HL7 International. *US Core* 9.0.0, page "Writing Vital Signs" (Informative).
   <https://hl7.org/fhir/us/core/writing-vital-signs.html>
5. HL7 International. *Personal Health Device FHIR IG* 2.0.0 (STU2), 2026-04-01.
   `PhdBaseObservation`, CodeSystem `PhdObservationCategories`.
   <https://hl7.org/fhir/uv/phd/>
6. HL7 International / Patient Empowerment Work Group. *Personal Health Records
   Implementation Guide* (`hl7.fhir.uv.phr`), 1.0.0-ballot2, CI build generated
   2026-09-17, page "Patient Generated Health Data (PGHD)".
   <https://build.fhir.org/ig/HL7/personal-health-record-format-ig/en/pghd.html>
7. HL7 International. *FHIR R4* 4.0.1, "Security Labels".
   <https://hl7.org/fhir/R4/security-labels.html>; HL7 Terminology,
   CodeSystem `v3-ActReason` (code `HTEST`).
