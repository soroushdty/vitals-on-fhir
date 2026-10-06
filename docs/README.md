# docs — vitals-on-fhir

This directory contains:
- Software Requirements Specification (SRS)
- Architecture Decision Records (ADRs)
- Protocol source citations (BLE, FHIR, LOINC, UCUM)

Protocol knowledge must be cited here, not only in code comments.

## Guides

- [architecture.md](architecture.md) — how the pipeline works, the extension points (ABCs and shipped defaults), and the project structure.
- [fhir-api.md](fhir-api.md) — the read-only FHIR REST API endpoints and an example US Core heart-rate Observation.
- [device-compatibility.md](device-compatibility.md) — supported devices and the known limitations of the standard Bluetooth channel.
- [roadmap.md](roadmap.md) — planned vital signs, adapters, and integrations beyond the MVP.
- [standards-and-related-work.md](standards-and-related-work.md) — the standards this project builds on and related projects.

## Architecture Decision Records

- [ADR-0001](adr-0001-open-phase-2-home-health-devices.md) — open roadmap phase 2 (home health devices).
- [ADR-0002](adr-0002-mark-patient-generated-and-simulated-observations.md) — mark Observations as patient-generated (`performer`, PHD category) and simulated data as test data (`HTEST`).

## Protocol source citations

- [Bluetooth Heart Rate Measurement (0x2A37)](protocol-heart-rate-measurement.md) — Bluetooth SIG
  specifications used to implement the heart-rate parser (FR-3a.6).
