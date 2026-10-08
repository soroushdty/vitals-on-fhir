# FHIR API and output

## FHIR output

Each accepted heart-rate measurement becomes an Observation conforming to the [US Core Heart Rate profile](http://hl7.org/fhir/us/core/StructureDefinition/us-core-heart-rate):

```json
{
  "resourceType": "Observation",
  "id": "example-hr-1",
  "meta": {
    "profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-heart-rate"]
  },
  "status": "final",
  "category": [{
    "coding": [{
      "system": "http://terminology.hl7.org/CodeSystem/observation-category",
      "code": "vital-signs",
      "display": "Vital Signs"
    }]
  }, {
    "coding": [{
      "system": "http://hl7.org/fhir/uv/phd/CodeSystem/PhdObservationCategories",
      "code": "phd",
      "display": "PHD generated Observation"
    }]
  }],
  "code": {
    "coding": [{ "system": "http://loinc.org", "code": "8867-4", "display": "Heart rate" }]
  },
  "subject": { "reference": "Patient/local-patient" },
  "performer": [{ "reference": "Patient/local-patient" }],
  "device": { "reference": "Device/smart-band-10" },
  "effectiveDateTime": "2026-09-21T18:04:12.345Z",
  "issued": "2026-09-21T18:04:12.402Z",
  "valueQuantity": {
    "value": 72,
    "unit": "/min",
    "system": "http://unitsofmeasure.org",
    "code": "/min"
  }
}
```

`effectiveDateTime` is when the measurement was taken. `issued` is when `vitals-on-fhir` produced the Observation.

Every Observation is marked as patient-generated health data: the second `category` (`phd`, from the HL7 Personal Health Device IG) says it came from a personal health device through a gateway, and `performer` names the patient who took the reading. Readings from the mock adapters, and their Device, also carry the security label `HTEST` (`http://terminology.hl7.org/CodeSystem/v3-ActReason`, "test health data") in `meta.security`, so simulated data can't be mistaken for real measurements. See [ADR-0002](adr-0002-mark-patient-generated-and-simulated-observations.md).

## FHIR API (read-only)

All requests require `Authorization: Bearer <token>`, except in demo mode (no `VOF_API_TOKEN` set, mock adapter only), where no token is needed. Responses use `application/fhir+json`, and search results are FHIR `Bundle`s (`type: searchset`).

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/fhir/metadata` | `CapabilityStatement` |
| `GET` | `/fhir/Observation` | Search by `code`, `date`, `_sort=-date`, `_count` (see [Search parameters](#search-parameters)) |
| `GET` | `/fhir/Observation/{id}` | Read one Observation |
| `GET` | `/fhir/Patient/{id}` | Read the configured local Patient |
| `GET` | `/fhir/Device/{id}` | Read the connected Device. Built from the adapter on each request, so a Bluetooth device's address appears once the device has been found |

```bash
curl -H "Authorization: Bearer $VOF_API_TOKEN" \
  "http://localhost:8000/fhir/Observation?code=http://loinc.org|8867-4&_sort=-date&_count=10"
```

### Search parameters

| Parameter | Behaviour |
|---|---|
| `code` | A FHIR token. `8867-4` matches that code in any system; `http://loinc.org\|8867-4` needs the system too; `\|8867-4` matches a coding without a system; `http://loinc.org\|` matches any LOINC-coded Observation. Every coding is searched, so SpO2 is found by `59408-5` or `2708-6` |
| `date` | Filters `effectiveDateTime`. A value covers the range its precision implies: `2026-10` is the month, `2026-10-07` the day, `2026-10-07T12:00:00Z` one second. The prefixes `eq` (the default), `ge`, `gt`, `le` and `lt` compare that range with the reading's time, so `gt2026-10-07` means from 8 October on. Repeat the parameter for a range: `date=ge2026-10-01&date=lt2026-11-01`. A value without a UTC offset is in the zone set by `VOF_SEARCH_TIMEZONE` (default `UTC`) |
| `_sort` | `-date` only (newest first) |
| `_count` | Page size. `Bundle.total` still counts every match |

An invalid `date` returns 400 with an `OperationOutcome` (`invalid`), and so do the prefixes `ne`, `sa`, `eb` and `ap` (`not-supported`). Other search parameters are ignored. In a URL, write the `+` of a UTC offset as `%2B` (an unencoded `+` is also accepted).
