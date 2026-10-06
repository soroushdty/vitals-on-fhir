# Standards and related work

## Standards

- [HL7 FHIR R4](https://hl7.org/fhir/R4/) and the [US Core](https://www.hl7.org/fhir/us/core/) vital-signs profiles (checked against US Core 9.0.0)
- [LOINC](https://loinc.org/) `8867-4` (Heart rate) and [UCUM](https://ucum.org/) units
- Bluetooth SIG Heart Rate Service / Heart Rate Measurement characteristic (`0x180D` / `0x2A37`)
- [HL7 Personal Health Device (PHD) Implementation Guide](https://hl7.org/fhir/uv/phd/) 2.0.0: the `phd` Observation category marks patient-generated data, and the `HTEST` security label marks simulated data ([ADR-0002](adr-0002-mark-patient-generated-and-simulated-observations.md))

## Related work

- Open-source HL7 FHIR framework for real-time biomedical signal acquisition (MDPI *Applied Sciences*, 2025): <https://www.mdpi.com/2076-3417/15/23/12803>
- Medplum, "From BLE to FHIR": <https://www.medplum.com/blog/ble-to-fhir-anybio-medplum>
- Gadgetbridge (open-source companion app for many wearables): <https://codeberg.org/Freeyourgadget/Gadgetbridge>
