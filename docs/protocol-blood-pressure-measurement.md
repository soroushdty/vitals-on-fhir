# Protocol source citation — Bluetooth Blood Pressure Measurement (0x2A35)

This document records the Bluetooth SIG specifications used to implement
`BloodPressureMeasurementParser` (`src/vitals_on_fhir/adapters/bp_parser.py`) and
the blood-pressure BLE acquisition path (`src/vitals_on_fhir/adapters/ble.py`,
via the reusable `BleConnection` lifecycle).

Satisfies requirement **FR-HH-5** and the protocol-sourcing rules in
`.kiro/steering/security-privacy.md`: BLE characteristic formats and GATT
service UUIDs come only from published Bluetooth SIG specifications, cited here
with specification name, version, and URL or publication date.

All protocol knowledge in the parser (flags byte, IEEE-11073 16-bit SFLOAT
value encoding, systolic/diastolic/mean-arterial-pressure fields, unit
selection, the optional date-time field, and field offsets) derives from these
published specifications. No code was copied, translated, or closely paraphrased
from other projects or vendor SDKs.

## Cited specifications

| Specification | What it defines | Version | Reference |
|---------------|-----------------|---------|-----------|
| Blood Pressure Service (BLS) | The Blood Pressure Service (`0x1810`) and its Blood Pressure Measurement characteristic (`0x2A35`) | 1.1.1 (adopted 2020-06-16) | <https://www.bluetooth.com/specifications/specs/blood-pressure-service-1-1-1/> |
| Blood Pressure Profile (BLP) | The profile that uses the Blood Pressure Service, including the Collector/Sensor roles | 1.1.1 (adopted 2020-06-16) | <https://www.bluetooth.com/specifications/specs/blood-pressure-profile-1-1-1/> |
| GATT Specification Supplement (GSS) | Field structure of the Blood Pressure Measurement characteristic: flags byte, the three SFLOAT compound values (systolic, diastolic, MAP), unit flag, timestamp, pulse rate, user id, and measurement status | Current published revision | <https://www.bluetooth.com/specifications/specs/gatt-specification-supplement/> |
| Assigned Numbers | UUID assignments for the Blood Pressure Service (`0x1810`) and Blood Pressure Measurement characteristic (`0x2A35`) | Current published revision | <https://www.bluetooth.com/specifications/assigned-numbers/> |
| ISO/IEEE 11073-20601 | The 16-bit SFLOAT (short float) medical-device value encoding: 4-bit signed exponent and 12-bit signed mantissa, and the reserved special values (NaN, NRes, ±INFINITY) | Personal Health Data Exchange Protocol | <https://standards.ieee.org/ieee/11073-20601/5619/> |

## How the specifications map to the parser

The Blood Pressure Measurement characteristic (`0x2A35`) payload begins with a
flags byte, followed by three mandatory SFLOAT compound values (systolic,
diastolic, mean arterial pressure), then optional fields. The parser decodes
each field per the GATT Specification Supplement and the IEEE-11073 SFLOAT
definition:

- **Bit 0 — Blood Pressure Units**: `0` = values are in mmHg; `1` = values are in
  kPa. When kPa is indicated, the parser normalizes systolic and diastolic to
  `mm[Hg]` before constructing the reading.
- **Bit 1 — Timestamp present**: when set, a 7-byte org.bluetooth date-time field
  follows the three SFLOATs. The parser uses it as the reading's measurement
  (`effective`) time, enabling store-and-forward.
- **Bit 2 — Pulse Rate present**, **Bit 3 — User ID present**, **Bit 4 —
  Measurement Status present**: these optional fields are accounted for when
  computing the minimum payload length, but are not used by this parser.
- **SFLOAT values**: each of systolic, diastolic, and MAP is a 16-bit SFLOAT (a
  4-bit signed exponent and a 12-bit signed mantissa). Reserved mantissa values
  (NaN, NRes, ±INFINITY, and the reserved value) do not represent a usable number.
  Only systolic and diastolic are used; MAP is device-derived and is intentionally
  not modelled.

Payloads too short for the fields their flags byte declares, carrying a reserved
or unusable SFLOAT for the systolic or diastolic value, or carrying an invalid
calendar date-time when the timestamp flag is set, are rejected (`parse` returns
`None`) so the adapter drops them without yielding a reading.

## Timezone assumption

The org.bluetooth date-time field carries no timezone. For the project's local,
single-user home-monitoring model, a decoded device timestamp is interpreted as
the **host's local time** and returned timezone-aware with the host's local
offset. This is a documented limitation: a reading actually taken in a different
timezone than the host would be mislabeled. See
`.kiro/specs/home-health-devices/design.md` and `docs/brief-config-file.md`
(a future optional `timezone` config key with `local` default).

## Trademark notice

Bluetooth® is a registered trademark of Bluetooth SIG, Inc. This project is not
affiliated with or endorsed by Bluetooth SIG. Bluetooth terminology is used here
only to describe compatibility with published specifications.
