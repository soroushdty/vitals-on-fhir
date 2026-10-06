# Protocol source citation — Bluetooth Temperature Measurement (0x2A1C)

This document records the Bluetooth SIG specifications used to implement
`TemperatureMeasurementParser` (`src/vitals_on_fhir/adapters/temp_parser.py`)
and the body-temperature BLE acquisition path (`src/vitals_on_fhir/adapters/ble.py`,
via the reusable `BleConnection` lifecycle, composed by
`HealthThermometerBleAdapter`). The IEEE-11073 32-bit FLOAT decoding lives in
`src/vitals_on_fhir/adapters/sfloat.py` (`decode_float`), alongside the 16-bit
SFLOAT decoding shared by the blood-pressure and pulse-oximeter parsers. The
7-byte org.bluetooth date-time decoding is shared with the blood-pressure parser
through `src/vitals_on_fhir/adapters/datetime_field.py` (`decode_timestamp`).

Satisfies requirements **FR-TEMP-3**, **FR-TEMP-1**, **FR-TEMP-8**, and
**NFR-TEMP-4**, and the protocol-sourcing rules in
`.kiro/steering/security-privacy.md`: BLE characteristic formats and GATT
service UUIDs come only from published Bluetooth SIG specifications, cited here
with specification name, version, and URL or publication date.

All protocol knowledge in the parser (flags byte, IEEE-11073 32-bit FLOAT value
encoding, the unit selection, the optional timestamp and temperature-type
fields, and field offsets) derives from these published specifications. No code
was copied, translated, or closely paraphrased from other projects or vendor
SDKs.

## Cited specifications

| Specification | What it defines | Version | Reference |
|---------------|-----------------|---------|-----------|
| Health Thermometer Service (HTS) | The Health Thermometer Service (`0x1809`) and its Temperature Measurement characteristic (`0x2A1C`) | 1.0 (adopted 2011-06-14) | <https://www.bluetooth.com/specifications/specs/health-thermometer-service-1-0/> |
| Health Thermometer Profile (HTP) | The profile that uses the Health Thermometer Service, including the Collector/Sensor roles | 1.0 (adopted 2011-06-14) | <https://www.bluetooth.com/specifications/specs/health-thermometer-profile-1-0/> |
| GATT Specification Supplement (GSS) | Field structure of the Temperature Measurement characteristic: flags byte, the FLOAT temperature value, unit flag, the optional 7-byte date-time (timestamp) field, and the optional temperature-type field, with their offsets | Current published revision | <https://www.bluetooth.com/specifications/specs/gatt-specification-supplement/> |
| Assigned Numbers | UUID assignments for the Health Thermometer Service (`0x1809`) and the Temperature Measurement characteristic (`0x2A1C`) | Current published revision | <https://www.bluetooth.com/specifications/assigned-numbers/> |
| ISO/IEEE 11073-20601 | The 32-bit FLOAT medical-device value encoding: 8-bit signed exponent and 24-bit signed mantissa, and the reserved special values (NaN, NRes, ±INFINITY, and the reserved value) | Personal Health Data Exchange Protocol | <https://standards.ieee.org/ieee/11073-20601/5619/> |

## How the specifications map to the parser

The Temperature Measurement characteristic (`0x2A1C`) payload begins with a
flags byte, followed by a mandatory 32-bit FLOAT temperature value (offset 1),
then optional fields. The parser decodes each field per the GATT Specification
Supplement and the IEEE-11073 FLOAT definition:

- **Bit 0 — Temperature Units**: `0` = the value is in degrees Celsius; `1` = the
  value is in degrees Fahrenheit. When Fahrenheit is indicated, the parser
  normalizes the value to Celsius with `(value − 32) × 5 / 9` before
  constructing the reading, so downstream validation and FHIR output are always
  in Celsius (UCUM `Cel`).
- **Bit 1 — Timestamp present**: when set, a 7-byte org.bluetooth date-time field
  follows the FLOAT value. The parser uses it as the reading's measurement
  (`effective`) time, enabling store-and-forward. When absent, the parser stamps
  the reading with the processing time (an injectable, timezone-aware local
  clock).
- **Bit 2 — Temperature Type present**: when set, a 1-byte Temperature Type field
  (where on the body the temperature was taken) follows the timestamp, or the
  FLOAT when there is no timestamp. The parser decodes it into the reading's
  `body_site`, which the mapper writes to `Observation.bodySite` (see
  [Measurement site](#measurement-site-temperature-type) below).
- **FLOAT value**: the temperature is a 32-bit FLOAT (an 8-bit signed exponent and
  a 24-bit signed mantissa). Reserved mantissa values (NaN, NRes, ±INFINITY, and
  the reserved value) do not represent a usable number and cause the value to be
  rejected.

Payloads too short for the fields their flags byte declares, carrying a reserved
or unusable FLOAT temperature value, or carrying an invalid calendar date-time
when the timestamp flag is set, are rejected (`parse` returns `None`) so the
adapter drops them without yielding a reading.

## Measurement site (Temperature Type)

Readings taken at different sites are not directly comparable, so the site is
carried into FHIR as `Observation.bodySite` (#11, ADR-0006).

**Values.** GATT Specification Supplement, version date 2026-09-09, §3.242.1,
Table 3.370 "Temperature Type Description field" (the Temperature Measurement
field "is the same as the format of the Temperature Type characteristic",
§3.239). The values correspond to the Temperature Type descriptions in
IEEE 11073-10408-2008.

**Codes.** Each site with a specific location maps to one SNOMED CT body-structure
concept. All were checked on 2026-10-06 against SNOMED CT International Edition
2025-02-01 on `tx.fhir.org` (`CodeSystem/$lookup`: active, display is the
preferred term). The HL7 FHIR validator 6.10.4 (US Core 9.0.0, Body Temperature
profile) then reported no errors for an Observation with each code.

| GSS value | GSS definition | SNOMED CT code | SNOMED CT display | Notes |
|-----------|----------------|----------------|-------------------|-------|
| 0 | Reserved for Future Use | — | — | No `bodySite` |
| 1 | Armpit | `91470000` | Axillary region structure | |
| 2 | Body (general) | — | — | No `bodySite`: no specific site, so nothing to guess |
| 3 | Ear (usually earlobe) | `48800003` | Ear lobule structure | Follows the GSS's "usually earlobe" |
| 4 | Finger | `7569003` | Finger structure | |
| 5 | Gastrointestinal Tract | `122865005` | Gastrointestinal tract structure | |
| 6 | Mouth | `74262004` | Oral cavity structure | Oral readings are taken inside the mouth, so the oral cavity rather than "Mouth region structure" (`123851003`) |
| 7 | Rectum | `34402009` | Rectum structure | |
| 8 | Toe | `29707007` | Toe structure | |
| 9 | Tympanum (ear drum) | `42859004` | Tympanic membrane structure | |
| 10–255 | Reserved for Future Use | — | — | No `bodySite` |

An absent Temperature Type field also gives no `bodySite`.

**The static Temperature Type characteristic (not read yet).** HTS 1.0 §3.2: "There
are two exclusive methods to enable a Thermometer to provide temperature type
information to a Collector. Either one method or the other is used, but not
both." A thermometer whose site cannot change exposes the separate Temperature
Type characteristic (`0x2A1D`) and leaves the field out of each measurement
(§3.1.1.4). The adapter does not read that characteristic yet, so readings from
such thermometers carry no `bodySite`. Reading it once after connecting would
need a `BleConnection` change, which is left for a follow-up.

## Fahrenheit → Celsius normalization

Devices may report in either unit (flags bit 0). The parser normalizes any
Fahrenheit-flagged value to Celsius at parse time using `(value − 32) × 5 / 9`,
so the constructed `BodyTemperature` always carries Celsius (UCUM `Cel`) and the
plausibility validator always compares against Celsius bounds regardless of the
device's reporting unit.

## Timezone assumption

The org.bluetooth date-time field carries no timezone. As with blood pressure, a
decoded device timestamp is interpreted as the **host's local time** and returned
timezone-aware with the host's local offset. This is a documented limitation and
follows the same convention as the blood-pressure parser; see
`docs/protocol-blood-pressure-measurement.md` for the full rationale and the
shared `decode_timestamp` helper.

## Range rationale — the `(10.0, 47.0)` °C plausibility bounds

The default plausibility range for `BodyTemperature` is `(10.0, 47.0)` °C. These
are **physical-plausibility bounds, not clinical thresholds.** Their only job is
to reject values that could not have come from a live human body — decode errors,
sensor malfunction, or an ambient/wrong-sensor reading — not to judge whether a
value is normal, high, or low for any particular person. They are overridable via
`VOF_TEMP_MIN` / `VOF_TEMP_MAX`.

The bounds are grounded in the documented human-survival envelope, with a small
margin on each side:

- **Lower bound `10.0` °C** sits just below the lowest core temperatures from which
  people have been resuscitated neurologically intact after accidental
  hypothermia. Reported cases include a core temperature of about `11.8` °C in a
  young child (<https://pubmed.ncbi.nlm.nih.gov/33084865/>) and roughly `13.7` °C
  in an adult — the widely cited Anna Bågenholm case
  (<https://pubmed.ncbi.nlm.nih.gov/32482520/>). Placing the bound just under the
  lowest survivable value means a genuinely cold reading is never discarded, while
  clearly non-physiological values (a `0` °C decode artifact, or a room-temperature
  sensor read) still fall outside the range.
- **Upper bound `47.0` °C** sits just above the highest core temperature recorded
  in a heat-stroke survivor: `46.5` °C, a case documented in 1980
  (<https://www.guinnessworldrecords.com/world-records/67749-highest-body-temperature>;
  see also <https://en.wikipedia.org/wiki/Hyperthermia> and the Emergency Medicine
  case report at <https://pubmed.ncbi.nlm.nih.gov/7073052/>). Placing the bound a
  little above the highest survivable value keeps every plausible fever within
  range while still rejecting non-physiological high values.

Content was rephrased for compliance with licensing restrictions; the sources are
paraphrased and linked inline above.

## Trademark notice

Bluetooth® is a registered trademark of Bluetooth SIG, Inc. This project is not
affiliated with or endorsed by Bluetooth SIG. Bluetooth terminology is used here
only to describe compatibility with published specifications.
