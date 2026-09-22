---
inclusion: fileMatch
fileMatchPattern: "src/vitals_on_fhir/fhir/**,src/vitals_on_fhir/vitals/**,src/vitals_on_fhir/api/**"
---

# FHIR conventions — vitals-on-fhir

## Version and profiles

- FHIR version: **R4 (4.0.1)**. Use `fhir.resources` R4B-compatible models; target R4 4.0.1 semantics throughout.
- Every Observation must conform to the relevant **US Core vital-signs profile** declared in the vital-sign class's `us_core_profile` class variable.
- Every Observation must include the base **vital-signs category** coding regardless of which profile it conforms to.
- Generated resources must validate before being served. Run `fhir.resources` model validation at construction time; do not serve resources that fail it.

## Canonical Observation shape

The following fields are required on every Observation produced by this project. Field order follows the FHIR spec.

```json
{
  "resourceType": "Observation",
  "id": "<uuid>",
  "meta": {
    "profile": ["<vital_class.us_core_profile>"]
  },
  "status": "final",
  "category": [{
    "coding": [{
      "system": "http://terminology.hl7.org/CodeSystem/observation-category",
      "code": "vital-signs",
      "display": "Vital Signs"
    }]
  }],
  "code": {
    "coding": [{
      "system": "http://loinc.org",
      "code": "<vital_class.loinc_code>",
      "display": "<human-readable name>"
    }]
  },
  "subject": { "reference": "Patient/<VOF_PATIENT_ID>" },
  "device":  { "reference": "Device/<device_id>" },
  "effectiveDateTime": "<vital.effective as ISO 8601 UTC>",
  "issued": "<processing time as ISO 8601 UTC>",
  "valueQuantity": {
    "value": <vital.value>,
    "unit": "<display unit>",
    "system": "http://unitsofmeasure.org",
    "code": "<vital_class.ucum_unit>"
  }
}
```

Rules:
- `status` is always `"final"` for MVP measurements.
- `effectiveDateTime` comes from `vital.effective` (timezone-aware; convert to UTC ISO 8601).
- `issued` is set by the mapper at processing time, not by the adapter. Always set both fields.
- `subject` and `device` are relative references only — no absolute URLs in the MVP.
- Do not add extra fields, extensions, or narrative (`text`) unless a US Core profile explicitly requires them.

## How class metadata drives mapping

`ScalarVitalMapper` reads directly from the vital-sign class's `ClassVar` metadata:

| FHIR field | Source |
|-----------|--------|
| `meta.profile` | `vital_class.us_core_profile` |
| `code.coding[0].code` | `vital_class.loinc_code` |
| `code.coding[0].system` | hardcoded `"http://loinc.org"` |
| `valueQuantity.code` | `vital_class.ucum_unit` |
| `valueQuantity.system` | hardcoded `"http://unitsofmeasure.org"` |
| `category` | hardcoded vital-signs coding |

A new `ScalarVital` subclass with correct metadata automatically produces a valid Observation with no mapper code.

## Device and Patient handling

- The **Patient** resource is a minimal synthetic resource built from `VOF_PATIENT_ID`. It has `resourceType`, `id`, and no clinical data. `build_patient(patient_id)` in `fhir/builders.py` constructs it.
- The **Device** resource is built from `DeviceInfo` (manufacturer, model, identifiers). `build_device(device_info)` in `fhir/builders.py` constructs it. The Device `id` is derived deterministically from `device_info` (e.g. slugified model name); it must be stable across restarts within a session.
- Both resources are constructed at startup in `cli.py` and passed to the mapper as reference strings (`"Patient/<id>"`, `"Device/<id>"`). They are not regenerated per observation.

## ID strategy

- Observation IDs are **UUIDs (v4)**, generated at mapper time, unique per Observation.
- Patient and Device IDs are short, stable, human-readable strings derived from config (`VOF_PATIENT_ID`) or device info. Do not use UUIDs for Patient/Device.
- IDs are strings; do not use numeric or sequential IDs.

## Bundle and search behavior

- Search results are returned as a `Bundle` with `type: "searchset"`.
- The Bundle `total` field reflects the number of matching entries, not the page size.
- Each entry has `fullUrl` set to `"<base_url>/fhir/Observation/<id>"` and `resource` containing the full Observation.
- Supported search parameters for `GET /fhir/Observation`:

| Parameter | Behavior |
|-----------|---------|
| `code` | Filter by `system\|code`, e.g. `http://loinc.org\|8867-4` |
| `date` | Filter by `effectiveDateTime`; supports `ge`, `le`, `gt`, `lt` prefixes |
| `_sort` | `-date` (descending effectiveDateTime) is the only supported value in the MVP |
| `_count` | Limit result set size; default is all results up to `VOF_STORE_MAX` |

- Unsupported search parameters are ignored silently (do not return an error).
- `GET /fhir/metadata` returns a `CapabilityStatement` documenting the supported endpoints and search parameters.

## OperationOutcome for errors

Return a `OperationOutcome` resource (via `build_operation_outcome()`) for all error responses, including:
- 401 Unauthorized (missing or invalid token)
- 404 Not Found (resource does not exist)
- 400 Bad Request (malformed request parameters)

Structure:

```json
{
  "resourceType": "OperationOutcome",
  "issue": [{
    "severity": "<fatal|error|warning|information>",
    "code": "<issue-type code>",
    "diagnostics": "<human-readable message>"
  }]
}
```

Use issue-type codes from the FHIR value set (e.g. `"security"` for auth failures, `"not-found"` for 404, `"invalid"` for 400). Never include secret values, stack traces, or internal system details in `diagnostics`.

## Validation before serving

Construct resources using `fhir.resources` model classes. Pydantic validation runs at construction time. Do not disable validation or catch `ValidationError` silently. If a resource fails to construct, log the error at `ERROR` level and return a 500 OperationOutcome — do not serve an invalid resource.

## Choosing codes for a new vital sign

Follow this decision process when adding a new vital-sign class:

1. **LOINC code**: use the LOINC term for the specific measurement panel (e.g. `59408-5` for SpO2). Check [loinc.org](https://loinc.org) for the current preferred term. Cite the LOINC release version in `docs/`.
2. **UCUM unit**: use the UCUM code, not the display string (e.g. `/min`, `%`, `Cel`, `kg`). Verify at [ucum.org](https://ucum.org). The `valueQuantity.unit` display string may be human-friendly, but `valueQuantity.code` must be the UCUM code.
3. **US Core profile URL**: find the profile in the [US Core Implementation Guide](https://www.hl7.org/fhir/us/core/). Use the canonical URL exactly as published. If no US Core profile exists for the measurement, use the base FHIR vital-signs profile (`http://hl7.org/fhir/StructureDefinition/vitalsigns`) as a fallback and document the decision in `docs/`.
4. Record sources in `docs/` before adding the code to the class.

## Content-type

All API responses use `Content-Type: application/fhir+json`. This applies to both successful responses and error OperationOutcomes. Do not use `application/json`.
