<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# ADR-0006 — Carry the thermometer's measurement site into `Observation.bodySite`

- **Status:** Accepted
- **Date:** 2026-10
- **Deciders:** Soroush Dianaty
- **Context tags:** fhir, terminology, ble
- **Issue:** #11

## Context

Bluetooth thermometers can report where a temperature was taken, for example the
armpit, mouth, or ear drum, in the Temperature Type field of each Temperature
Measurement. The parser skipped the field, so every body-temperature Observation
arrived with no site. Readings taken at different sites are not directly
comparable, so a clinician cannot interpret the value safely without the site.

The HL7 Personal Health Records IG's PGHD page [1] describes PGHD from the major
sources (HealthKit, Health Connect, Open mHealth / IEEE 1752, Kanta PHR) as data
type, value with unit, and metadata, and maps measurement context to FHIR elements
such as `bodySite` and `method` *(paraphrased, as summarised in #11)*. That page
is an informative CI build, not a published IG. Under `fhir-conventions.md` it
could not on its own justify a field that US Core does not require.

### Sources reviewed (2026-10-06)

- **GATT Specification Supplement**, version date 2026-09-09, §3.242.1,
  Table 3.370 [2]: Temperature Type values 1 Armpit, 2 Body (general), 3 Ear
  (usually earlobe), 4 Finger, 5 Gastrointestinal Tract, 6 Mouth, 7 Rectum, 8 Toe,
  9 Tympanum (ear drum); 0 and 10–255 reserved.
- **Health Thermometer Service 1.0**, §3.1.1.4 and §3.2 [3]: a thermometer
  provides the site either in each measurement (a site that can change) or as
  the static Temperature Type characteristic, "but not both".
- **SNOMED CT International Edition 2025-02-01**, via `tx.fhir.org`: each chosen
  concept is active, and its display is the preferred term.
- **HL7 FHIR validator 6.10.4** (FHIR 4.0.1, US Core 9.0.0, Body Temperature
  profile, terminology checking on): no errors for an Observation with each code.
  A made-up code and a wrong display name were both reported as errors, so the
  check is real.

## Decision

1. **The parser decodes Temperature Type into `body_site`.** This is a
   `BodySite` member: a SNOMED CT code and display, kept in the domain layer like
   the LOINC codes on vital classes. The field is on `VitalSign`, so any device
   can report a site later.
2. **Both mappers write `Observation.bodySite`** as one SNOMED CT coding when a
   site is known, and leave it out otherwise.
3. **No guessing.** "Body (general)", reserved values, and an absent field give no
   `bodySite`.
4. **Code choices** are listed in `docs/protocol-body-temperature-measurement.md`.
   Two needed judgement: "Ear (usually earlobe)" uses *Ear lobule structure*,
   following the GSS wording; "Mouth" uses *Oral cavity structure*, because oral
   readings are taken inside the mouth.
5. **`fhir-conventions.md` is amended**: a core Observation element carrying
   context the device itself reports (such as `bodySite`) may be added when an
   ADR records the choice and the codes, and the validator accepts the result.

## Consequences

- Body-temperature Observations from thermometers that send a site carry
  `bodySite`, and a receiver can tell an oral reading from an axillary one.
- Thermometers that use the static Temperature Type characteristic still produce
  no `bodySite`, because the adapter does not read that characteristic. Reading it
  once after connecting needs a `BleConnection` change and is left for a
  follow-up.
- Site-specific LOINC codes (for example oral or axillary temperature) were not
  added to `Observation.code`. US Core keeps `8310-5`, and `bodySite` carries the
  same information without a second code.
- Blood pressure (arm or wrist) could use the same field later, without mapper
  changes.

## References

1. HL7 International / Patient Empowerment Work Group. *Personal Health Records
   Implementation Guide* (`hl7.fhir.uv.phr`), version 1.0.0-ballot2, continuous
   build generated 2026-09-17, page "Patient Generated Health Data (PGHD)"
   (Informative). <https://build.fhir.org/ig/HL7/personal-health-record-format-ig/en/pghd.html>.
   This is a CI build, not an authorized publication.
2. Bluetooth SIG. GATT Specification Supplement, version date 2026-09-09.
   <https://www.bluetooth.com/specifications/gss/>
3. Bluetooth SIG. Health Thermometer Service, v1.0 (2011-05-24).
   <https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/HTS_v1.0/out/en/index-en.html>
