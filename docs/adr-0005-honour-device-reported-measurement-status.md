<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# ADR-0005 — Reject readings the device reports as untrustworthy or not final

- **Status:** Accepted
- **Date:** 2026-10
- **Deciders:** Soroush Dianaty
- **Context tags:** safety, validation, ble
- **Issue:** #7

## Context

Blood-pressure cuffs and pulse oximeters can report the quality of each reading in
status bitfields: Measurement Status for both, and Device and Sensor Status for
oximeters. The parsers counted these fields for the payload length but never read
them, so a reading the device itself called invalid was published as a `final`
Observation. The IFCC C-MHBLM recommendations [1] call for quality-assurance
protocols that ensure the accuracy and reliability of data from mobile health
devices before it is recorded in the EHR *(paraphrased, as summarised in #7)*. The
heart-rate path already respects the device's sensor-contact flag
(`SensorContactValidator`).

### Sources reviewed (2026-10-06)

- **GATT Specification Supplement**, version date 2026-09-09, §3.34.3, Table 3.55
  [2]: the Blood Pressure Measurement status bits (body movement, cuff too loose,
  irregular pulse, pulse-rate range, improper measurement position).
- **Pulse Oximeter Service 1.0.1**, Tables 3.4 and 3.5 [3]: the PLX Measurement
  Status bits (e.g. measurement ongoing, early estimated data, questionable,
  invalid) and Device and Sensor Status bits (e.g. low perfusion, sensor
  displaced). §3.2.1.5 states that "The Measurement Status bit definitions are the
  same as in Section 3.1.1.4", so the Continuous Measurement characteristic uses
  the same tables.

The per-bit tables, with the handling of each bit, are in
`docs/protocol-blood-pressure-measurement.md` and
`docs/protocol-pulse-oximeter-measurement.md`.

## Decision

1. **Parsers translate status bits into `device_issues`.** This is a set of
   `DeviceIssue` members on the reading, kept only for the bits that say the
   reading cannot be trusted or is not final. The domain object stays FHIR-free,
   like `HeartRate.sensor_contact`. The field is on `VitalSign`, so any adapter can
   use it.
2. **`DeviceStatusValidator` rejects any reading with issues.** Its reason names the
   issues and never the measurement value (NFR-5).
3. **Questionable and not-final readings are rejected**, not published with a
   non-final status. The project owner chose this on 2026-10-06. It is simpler,
   consistent with sensor contact, and keeps unreliable data out of the API and any
   future EHR.
4. **A BP cuff's "irregular pulse detected" flag is accepted.** The project owner
   chose this on 2026-10-06. It is a clinical finding (possible arrhythmia), not a
   fault in the reading, and rejecting it would drop every reading from a person
   with atrial fibrillation. The pulse-rate range bits are also accepted, because
   they concern pulse rate, which is not recorded.
5. **Other bits that are not issues** are accepted: PLX "validated data", "fully
   qualified data", and "extended display update ongoing". Reserved bits are
   ignored.
6. **PLX "data from measurement storage" is rejected.** A Continuous Measurement
   carries no timestamp, so a stored reading would get the wrong `effective` time.

## Consequences

- No reading that the device marks invalid, questionable, or not final becomes a
  `final` Observation. A device that sends no status behaves as before.
- Irregular-pulse information is not recorded anywhere yet. Recording it, for
  example as an Observation `interpretation` or a separate finding, would be a
  later issue.
- A third-party adapter can set `device_issues` to get the same protection.
- Publishing questionable readings with a lower status remains possible later, but
  would need a mapper path and a new ADR.

## References

1. Nichols JH, Assad RS, Becker J, Dabla PK, Gammie A, Gouget B, Heydlauf M,
   Homsak E, Korita I, Kotani K, Saatçi E, Stankovic S, Uygun ZO, AbdelWareth L.
   Integrating Patient-Generated Health Data from Mobile Devices into Electronic
   Health Records: Best Practice Recommendations by the IFCC Committee on Mobile
   Health and Bioengineering in Laboratory Medicine (C-MHBLM). *EJIFCC*.
   2024;35(4):324–328. PMID [39810897](https://pubmed.ncbi.nlm.nih.gov/39810897/);
   PMCID [PMC11726333](https://pmc.ncbi.nlm.nih.gov/articles/PMC11726333/).
2. Bluetooth SIG. GATT Specification Supplement, version date 2026-09-09.
   <https://www.bluetooth.com/specifications/gss/>
3. Bluetooth SIG. Pulse Oximeter Service, v1.0.1.
   <https://bluetooth.com/wp-content/uploads/Files/Specification/HTML/PLXS_v1.0.1/out/en/index-en.html>
