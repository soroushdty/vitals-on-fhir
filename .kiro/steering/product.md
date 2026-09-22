---
inclusion: always
---

# Product — vitals-on-fhir

## Mission

vitals-on-fhir is an open-source interoperability layer. It acquires vital signs from commercially available consumer wearables and home health devices through open, standardized channels and exposes them as HL7 FHIR R4 resources.

The project is about the bridge. Downstream applications, analytics, and clinical decision support are permanently out of scope. The MVP web dashboard is a demonstration consumer of the FHIR API, not the product itself.

## Not a medical device

vitals-on-fhir is a research and educational proof-of-concept for healthcare interoperability. It must not be used for diagnosis, treatment, or any clinical decision-making.

## Academic context

- Course: BMI 540, Biomedical Informatics and Data Science PhD / MS program, Arizona State University
- Team: Soroush Dianaty MD, Nusrat Ashrafi MS, Isha Uttham BS
- Instructor: Shetty Sheetal PhD
- A preprint is planned. Decisions, provenance, and traceability matter — keep requirement IDs in specs and changelogs.

## Users and use cases

| ID | Use case | MVP status |
|----|----------|-----------|
| UC-1 | Gym user monitoring their own heart rate in real time | Supported locally |
| UC-2 | Caregiver monitoring an elderly person at home | Demonstrated locally only |
| UC-3 | Clinician reviewing vitals during telehealth | Demonstrated locally only |

Remote access is a roadmap item. Do not imply it is supported in any documentation or UI.

## Functional requirements

| ID | Requirement |
|----|-------------|
| FR-1 | BLE device connection: discover, connect to, and maintain a BLE connection with one device; monitor connection state for the whole session. |
| FR-2 | Real-time acquisition: continuously receive heart-rate notifications via the standard Bluetooth Heart Rate Service (GATT 0x180D, characteristic 0x2A37) without user intervention. |
| FR-3 | Validation: parse each payload per the Bluetooth Heart Rate Measurement spec (flags byte: uint8/uint16 value format, sensor contact status, energy expended, RR intervals). Malformed payloads are dropped inside the adapter's parser. Well-formed readings pass through the validator chain, which rejects implausible values (default 20–250 bpm, configurable), readings without sensor contact, and duplicates. |
| FR-4 | FHIR Observation generation: convert each accepted reading to a FHIR R4 Observation conforming to the US Core Heart Rate profile: LOINC 8867-4, category vital-signs, UCUM `/min`, status final, subject = configured local Patient, device = Device resource. |
| FR-5 | Live dashboard: web dashboard showing latest heart rate, observation timestamp, and connection status. |
| FR-6 | Connection status monitoring: show disconnection; stop showing new values until reconnected; resume automatically. |
| FR-7 | Continuous monitoring: no manual refresh or restart needed. |
| FR-8 | Standardized representation: every processed measurement is represented as a FHIR Observation. No non-FHIR side channels for measurement data. |
| FR-9 | Mock data support: `MockAdapter`, a concrete adapter producing simulated vital signs so the full pipeline can be developed and tested without hardware. |
| FR-10 | Automated dashboard updates: server push via WebSocket; no page reload. |
| FR-11 | Read-only FHIR REST API: `GET /fhir/metadata` (CapabilityStatement), `GET /fhir/Observation` (search: `code`, `date`, `_sort=-date`, `_count`; returns a searchset Bundle), `GET /fhir/Observation/{id}`, `GET /fhir/Patient/{id}`, `GET /fhir/Device/{id}`. Content-type `application/fhir+json`. No write operations in the MVP. |
| FR-12 | Token authentication: a single configured bearer token (`VOF_API_TOKEN`) is required for every API request and for the dashboard WebSocket. Reject missing or invalid tokens with a FHIR OperationOutcome. |
| FR-13 | Extensibility: vital-sign types, device adapters, validators, FHIR mappers, stores, output sinks, and authenticators are all abstract base classes that consumers can subclass. Third-party adapters are selectable by fully qualified class path without modifying the repository. |

## Non-functional requirements

| ID | Requirement |
|----|-------------|
| NFR-1 | Performance: near-real-time; a new measurement should reach the dashboard promptly after BLE notification. |
| NFR-2 | Reliability: detect disconnection; reconnect and resume automatically. |
| NFR-3 | Usability: dashboard understandable by non-technical users. |
| NFR-4 | Interoperability: FHIR R4 (4.0.1), US Core vital-signs profiles, LOINC, UCUM. Generated resources must validate. |
| NFR-5 | Security: token auth; bind to 127.0.0.1 by default; no secrets in code or logs; no measurement values in logs above DEBUG level. |
| NFR-6 | Maintainability: architecture rules are enforced by automated tests (dependency directions, ABC contracts), not only by documentation. |

## MVP scope

### In scope

- Real-time heart rate via the standard Bluetooth Heart Rate Service (GATT `0x180D`)
- One connected device at a time
- Extensible object model (ABCs for vitals, adapters, validators, stores, sinks, auth)
- Concrete adapters: `MiBand10Adapter` (reference device) and `MockAdapter` (simulated data)
- Validation: plausible range, sensor contact, duplicate detection
- FHIR R4 Observation generation conforming to the US Core Heart Rate profile
- Local, read-only FHIR REST API with token authentication
- Live web dashboard via WebSocket

### Permanently out of scope

- Vital signs other than heart rate (class hierarchy must be ready for them; do not add logic for them in the MVP)
- Multiple simultaneous devices
- Patient management or clinical decision support
- Writing to external EHRs or FHIR servers
- Remote or cloud deployment
- Historical on-device data retrieval
- Proprietary or reverse-engineered device protocols
- Persistence beyond in-memory storage

## Roadmap (context only — do not plan work for these)

1. Heart rate from wearables via standard BLE Heart Rate Service — **MVP**
2. Home health devices via standard Bluetooth health profiles (BP, SpO2, temperature, weight)
3. Phone health aggregators (Android Health Connect, Apple HealthKit)
4. Persistence and outbound integration: durable stores, outbound FHIR sinks, SMART on FHIR auth, adapter entry-point discovery
5. Additional concrete adapters as separately licensed packages

The object model must accommodate all roadmap items without breaking changes. See `object-model.md` for specifics.

## License

AGPL-3.0-or-later. Every new source file must carry: `SPDX-License-Identifier: AGPL-3.0-or-later`.
