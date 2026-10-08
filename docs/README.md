# docs — vitals-on-fhir

This directory contains:
- Guides to how the project works and how to use it
- Architecture Decision Records (ADRs): decisions and their reasons
- Briefs: findings recorded before a decision, or ideas not yet scheduled
- Protocol source citations (BLE, FHIR, LOINC, UCUM)

The requirements (functional and non-functional, numbered `FR-*` / `NFR-*`) and the project's conventions are in the steering documents under [`.kiro/steering/`](../.kiro/steering/), starting with [`product.md`](../.kiro/steering/product.md). Each feature's design and task list is under [`.kiro/specs/`](../.kiro/specs/).

Protocol knowledge must be cited here, not only in code comments.

## Guides

- [architecture.md](architecture.md) — how the pipeline works, the extension points (ABCs and shipped defaults), and the project structure.
- [fhir-api.md](fhir-api.md) — the read-only FHIR REST API endpoints and an example US Core heart-rate Observation.
- [device-compatibility.md](device-compatibility.md) — supported devices and the known limitations of the standard Bluetooth channel.
- [roadmap.md](roadmap.md) — what has shipped, and the planned adapters and integrations.
- [standards-and-related-work.md](standards-and-related-work.md) — the standards this project builds on and related projects.

## Architecture Decision Records

- [ADR-0001](adr-0001-open-phase-2-home-health-devices.md) — open roadmap phase 2 (home health devices).
- [ADR-0002](adr-0002-mark-patient-generated-and-simulated-observations.md) — mark Observations as patient-generated (`performer`, PHD category) and simulated data as test data (`HTEST`).
- ADR-0003 — reserved for the session capture and review decision; see the [brief](brief-session-capture-and-review.md).
- [ADR-0004](adr-0004-attribute-multi-user-device-readings.md) — record only the configured user's readings from multi-user cuffs and scales (`VOF_DEVICE_USER_ID`); the device user ID is compared, never kept.
- [ADR-0005](adr-0005-honour-device-reported-measurement-status.md) — reject BP and SpO2 readings the device reports as untrustworthy or not final (`device_issues`); irregular pulse is accepted.
- [ADR-0006](adr-0006-temperature-measurement-site.md) — carry the thermometer's reported measurement site into `Observation.bodySite` as a SNOMED CT concept; omit it when no specific site is known.

## Briefs

- [Session capture, review and export](brief-session-capture-and-review.md) — findings for a downstream consumer; input for ADR-0003.
- [Standards alignment](brief-standards-alignment.md) — alignment with PGHD/EHR-integration guidance and SMART on FHIR.
- [Validation modes](brief-validation-modes.md) — per-vital plausibility vs personal or clinical relevance (an idea, not scheduled).
- [Configuration file](brief-config-file.md) — the case for `config.yaml` (promoted and implemented).

## Protocol source citations

Bluetooth SIG specifications used to implement each payload parser:

- [Heart Rate Measurement (0x2A37)](protocol-heart-rate-measurement.md) (FR-3a.6)
- [Blood Pressure Measurement (0x2A35)](protocol-blood-pressure-measurement.md)
- [PLX Continuous Measurement (0x2A5F)](protocol-pulse-oximeter-measurement.md)
- [Temperature Measurement (0x2A1C)](protocol-body-temperature-measurement.md)
- [Weight Measurement (0x2A9D)](protocol-weight-measurement.md)
