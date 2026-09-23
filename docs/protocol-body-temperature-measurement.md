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
- **Bit 2 — Temperature Type present**: when set, a 1-byte temperature-type field
  (measurement site) follows. It is accounted for when computing the minimum
  payload length, but is not decoded into the reading.
- **FLOAT value**: the temperature is a 32-bit FLOAT (an 8-bit signed exponent and
  a 24-bit signed mantissa). Reserved mantissa values (NaN, NRes, ±INFINITY, and
  the reserved value) do not represent a usable number and cause the value to be
  rejected.

Payloads too short for the fields their flags byte declares, carrying a reserved
or unusable FLOAT temperature value, or carrying an invalid calendar date-time
when the timestamp flag is set, are rejected (`parse` returns `None`) so the
adapter drops them without yielding a reading.

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
