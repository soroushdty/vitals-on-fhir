<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# ADR-0004 — Record only the configured user's readings from multi-user devices

- **Status:** Accepted
- **Date:** 2026-10
- **Deciders:** Soroush Dianaty
- **Context tags:** safety, privacy, ble, validation
- **Issue:** #8

(ADR-0003 is reserved for the session-capture decision; see
`brief-session-capture-and-review.md`.)

## Context

Shared blood-pressure cuffs and weight scales tag each reading with a one-byte,
device-assigned user ID. The parsers counted that byte for the payload length but
never read it. As a result, every reading was filed under the single configured
`VOF_PATIENT_ID`. On a household device, one person's measurements ended up in
another person's record. The IFCC C-MHBLM recommendations [1] warn that, without a
proper interface, device data can end up in the wrong record, and ask that
interfaces ensure the accuracy of data recorded in the EHR *(paraphrased, as
summarised in #8)*.

The user ID was never read for privacy reasons: no per-user identifier should
enter logs, storage, or FHIR. That intent still holds.

### Sources reviewed (2026-10-06)

- **Blood Pressure Service v1.1.1, §3.1.1.5** [2]: "The User ID field shall be
  included in the Blood Pressure Measurement characteristic if the device supports
  multiple users." "Special User ID value of 0xFF represents 'unknown user'."
- **Weight Scale Service v1.0.1** [3]: "The User ID field shall be included in the
  Weight Measurement characteristic if the device supports the Multiple Users
  feature". "A special User ID value of 0xFF represents 'unknown user'. This can be
  used for cases where a Weight Scale can be used for Guests."

So a single-user device never sends the field. Only multi-user devices are
affected by anything decided here.

## Decision

1. **A new optional setting, `VOF_DEVICE_USER_ID` (0–254)**, names the device user
   whose readings are recorded. 255 (`0xFF`, "unknown user") cannot be configured.
2. **Compare only.** The parser decodes the user ID, compares it with the setting,
   and keeps only the outcome on the reading (`device_user`: `MATCH`, `MISMATCH`,
   or `NOT_CONFIGURED`; `None` when the device sends no user ID). The ID itself is
   never kept on the reading, logged, stored, or put into FHIR.
3. **`DeviceUserValidator` rejects** `MISMATCH` (another user, or the unknown
   user) and `NOT_CONFIGURED`. Rejections go through the orchestrator's normal
   rejection log, which names the validator and a reason but never the user ID or
   the measurement value.
4. **Default when the setting is unset and the device sends a user ID: reject.**
   The project owner chose this on 2026-10-06. A multi-user device records nothing
   until the setting is set. The rejection reason names the setting to add.

### Alternatives not chosen

- **Accept with a warning when unset.** This keeps the first run easy, but readings
  could still land in the wrong record, and that is the failure this ADR exists to
  prevent.
- **Carry the ID on the reading and compare in the validator.** This is simpler,
  but the ID would enter the domain object, where a `repr` or a future log line
  could leak it.
- **Drop mismatches silently in the parser.** The user would get no feedback.
  Rejections should be logged like every other validation failure.
- **Route each device user to their own Patient.** This is out of scope, because
  the project models a single local patient.

## Implementation

- `vitals.DeviceUserMatch` (enum, with `compare`). `BloodPressure.device_user` and
  `BodyWeight.device_user` default to `None`.
- `BloodPressureMeasurementParser` and `WeightMeasurementParser` take
  `device_user_id`. `BloodPressureBleAdapter` and `WeightScaleBleAdapter` forward
  it, and `cli.py` passes `settings.device_user_id`.
- `validation.DeviceUserValidator` is in the default chain.
- `Settings.device_user_id`, documented in `.env.example`, `config.yaml.example`,
  and the README.
- Tests: both parsers at every user-ID offset, the validator, the setting, and an
  end-to-end check that the ID never appears in logs or a published Observation.

## Consequences

- A shared cuff or scale records only one person's readings, and others are
  visibly rejected.
- **Behaviour change:** a multi-user device that worked before records nothing
  until `VOF_DEVICE_USER_ID` is set. Single-user devices and the mock adapters are
  unaffected.
- A third-party adapter for a multi-user device should set `device_user` in the
  same way to get the same protection.
- Recording several household members, each as their own Patient, would need a
  user-to-Patient mapping and a new ADR.

## References

1. Nichols JH, Assad RS, Becker J, Dabla PK, Gammie A, Gouget B, Heydlauf M,
   Homsak E, Korita I, Kotani K, Saatçi E, Stankovic S, Uygun ZO, AbdelWareth L.
   Integrating Patient-Generated Health Data from Mobile Devices into Electronic
   Health Records: Best Practice Recommendations by the IFCC Committee on Mobile
   Health and Bioengineering in Laboratory Medicine (C-MHBLM). *EJIFCC*.
   2024;35(4):324–328. PMID [39810897](https://pubmed.ncbi.nlm.nih.gov/39810897/);
   PMCID [PMC11726333](https://pmc.ncbi.nlm.nih.gov/articles/PMC11726333/).
2. Bluetooth SIG. Blood Pressure Service, v1.1.1.
   <https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/BLS_v1.1.1/out/en/index-en.html>
3. Bluetooth SIG. Weight Scale Service, v1.0.1.
   <https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/WSS_v1.0.1/out/en/index-en.html>
