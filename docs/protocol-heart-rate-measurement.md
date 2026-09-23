# Protocol source citation — Bluetooth Heart Rate Measurement (0x2A37)

This document records the Bluetooth SIG specifications used to implement
`HeartRateMeasurementParser` (`src/vitals_on_fhir/adapters/parser.py`) and the
BLE acquisition path (`src/vitals_on_fhir/adapters/ble.py`).

Satisfies requirement **FR-3a.6** and the protocol-sourcing rules in
`.kiro/steering/security-privacy.md`: BLE characteristic formats and GATT
service UUIDs come only from published Bluetooth SIG specifications, cited here
with specification name, version, and URL or publication date.

All protocol knowledge in the parser (flags byte, uint8/uint16 value format,
sensor-contact status, energy-expended and RR-interval fields, field offsets)
derives from these published specifications. No code was copied, translated, or
closely paraphrased from other projects or vendor SDKs.

## Cited specifications

| Specification | What it defines | Version | Reference |
|---------------|-----------------|---------|-----------|
| Heart Rate Service (HRS) | The Heart Rate Service (`0x180D`) and its mandatory Heart Rate Measurement characteristic (`0x2A37`) | 1.0 (adopted 2011-07-12) | <https://www.bluetooth.com/specifications/specs/heart-rate-service-1-0/> |
| Heart Rate Profile (HRP) | The profile that uses the Heart Rate Service, including the Collector/Sensor roles | 1.0 (adopted 2011-07-12) | <https://www.bluetooth.com/specifications/specs/heart-rate-profile-1-0/> |
| GATT Specification Supplement (GSS) | Field structure of the Heart Rate Measurement characteristic: flags byte, uint8/uint16 value format, Sensor Contact Status, Energy Expended, and RR-Interval fields | Current published revision | <https://www.bluetooth.com/specifications/specs/gatt-specification-supplement/> |
| Assigned Numbers | UUID assignments for the Heart Rate Service (`0x180D`) and Heart Rate Measurement characteristic (`0x2A37`) | Current published revision | <https://www.bluetooth.com/specifications/assigned-numbers/> |

## How the specifications map to the parser

The Heart Rate Measurement characteristic (`0x2A37`) payload begins with a
flags byte, followed by the heart-rate value and optional fields. The parser
decodes each field per the GATT Specification Supplement:

- **Bit 0 — Heart Rate Value Format**: `0` = value is `uint8`; `1` = value is
  `uint16` (little-endian). Determines the size and offset of the value field.
- **Bits 1–2 — Sensor Contact Status**: whether sensor contact is supported and,
  if so, whether contact is currently detected. When contact is not supported by
  the flags byte, the parser sets `sensor_contact` to `None`.
- **Bit 3 — Energy Expended Status**: when set, a `uint16` Energy Expended field
  is present and shifts the offset of any following field.
- **Bit 4 — RR-Interval**: when set, one or more `uint16` RR-Interval values are
  present at the end of the payload.

Payloads too short for the fields their flags byte declares, or otherwise
malformed, are rejected (`parse` returns `None`) so the adapter drops them
without yielding a Reading.

## Trademark notice

Bluetooth® is a registered trademark of Bluetooth SIG, Inc. This project is not
affiliated with or endorsed by Bluetooth SIG. Bluetooth terminology is used here
only to describe compatibility with published specifications.
