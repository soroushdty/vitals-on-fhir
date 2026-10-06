# Protocol source citation — Bluetooth PLX Continuous Measurement (0x2A5F)

This document records the Bluetooth SIG specifications used to implement
`PlxContinuousMeasurementParser` (`src/vitals_on_fhir/adapters/plx_parser.py`)
and the pulse-oximeter BLE acquisition path (`src/vitals_on_fhir/adapters/ble.py`,
via the reusable `BleConnection` lifecycle, composed by
`PulseOximeterBleAdapter`). The IEEE-11073 16-bit SFLOAT decoding is shared with
the blood-pressure parser through `src/vitals_on_fhir/adapters/sfloat.py`.

Satisfies requirement **FR-SPO2-3** and **NFR-SPO2-4**, and the protocol-sourcing
rules in `.kiro/steering/security-privacy.md`: BLE characteristic formats and
GATT service UUIDs come only from published Bluetooth SIG specifications, cited
here with specification name, version, and URL or publication date.

All protocol knowledge in the parser (flags byte, the mandatory SpO2/pulse-rate
SFLOAT pair, the optional fast/slow SFLOAT pairs, the measurement-status and
device-and-sensor-status fields, the pulse-amplitude-index field, IEEE-11073
16-bit SFLOAT value encoding, and field offsets) derives from these published
specifications. No code was copied, translated, or closely paraphrased from
other projects or vendor SDKs.

## Cited specifications

| Specification | What it defines | Version | Reference |
|---------------|-----------------|---------|-----------|
| Pulse Oximeter Service (PLXS) | The Pulse Oximeter Service (`0x1822`) and its Continuous Measurement characteristic (`0x2A5F`) and Spot-Check Measurement characteristic (`0x2A5E`) | 1.0.1 (adopted 2019-12-17) | <https://www.bluetooth.com/specifications/specs/pulse-oximeter-service-1-0-1/> |
| Pulse Oximeter Profile (PLXP) | The profile that uses the Pulse Oximeter Service, including the Collector/Sensor roles | 1.0.1 (adopted 2019-12-17) | <https://www.bluetooth.com/specifications/specs/pulse-oximeter-profile-1-0-1/> |
| PLXS 1.0.1, §3.1.1.4–3.1.1.5 and §3.2.1.5–3.2.1.6 | The bit definitions of the Measurement Status (Table 3.4) and Device and Sensor Status (Table 3.5) fields, which the Continuous Measurement characteristic shares with Spot-Check. (The GATT Specification Supplement, version date 2026-09-09, does not define the PLX characteristics.) | 1.0.1 | <https://bluetooth.com/wp-content/uploads/Files/Specification/HTML/PLXS_v1.0.1/out/en/index-en.html> |
| Assigned Numbers | UUID assignments for the Pulse Oximeter Service (`0x1822`) and the PLX Continuous Measurement characteristic (`0x2A5F`) | Current published revision | <https://www.bluetooth.com/specifications/assigned-numbers/> |
| ISO/IEEE 11073-20601 | The 16-bit SFLOAT (short float) medical-device value encoding: 4-bit signed exponent and 12-bit signed mantissa, and the reserved special values (NaN, NRes, ±INFINITY) | Personal Health Data Exchange Protocol | <https://standards.ieee.org/ieee/11073-20601/5619/> |

## How the specifications map to the parser

The PLX Continuous Measurement characteristic (`0x2A5F`) payload begins with a
flags byte, followed by the mandatory **SpO2–PR normal** pair: an SpO2 SFLOAT
(offset 1) and a pulse-rate SFLOAT (offset 3). Optional fields follow, each
gated by a flag bit. The parser decodes the flags byte and the mandatory SpO2
SFLOAT per the GATT Specification Supplement and the IEEE-11073 SFLOAT
definition, and computes the minimum payload length from the declared optional
fields:

- **Bit 0 — SpO2PR-Fast present**: an extra SpO2/pulse-rate SFLOAT pair (4 bytes).
- **Bit 1 — SpO2PR-Slow present**: an extra SpO2/pulse-rate SFLOAT pair (4 bytes).
- **Bit 2 — Measurement Status present**: a 2-byte bitfield after the SpO2-PR
  pairs. Decoded; see the status tables below.
- **Bit 3 — Device and Sensor Status present**: a 3-byte bitfield after
  Measurement Status. Decoded; see the status tables below.
- **Bit 4 — Pulse Amplitude Index present**: a 2-byte SFLOAT.
- **SFLOAT values**: each SpO2 and pulse-rate value is a 16-bit SFLOAT (a 4-bit
  signed exponent and a 12-bit signed mantissa). Reserved mantissa values (NaN,
  NRes, ±INFINITY, and the reserved value) do not represent a usable number.
  Decoding is delegated to the shared `adapters/sfloat.py` module, the same
  implementation used by the blood-pressure parser.

Only the mandatory normal-pair SpO2 value is used to construct the reading. The
pulse-rate SFLOAT, the fast and slow pairs, and the pulse amplitude index are
accounted for when computing the minimum payload length, but are not modelled — SpO2 is a dimensionless
percentage in the PLX encoding, so the SFLOAT already yields the percentage
value with no unit normalization. (Pulse rate may be added later, additively, as
its own `ScalarVital` without changing this parser's output.)

Payloads too short for the fields their flags byte declares, or carrying a
reserved or unusable SFLOAT for the SpO2 value, are rejected (`parse` returns
`None`) so the adapter drops them without yielding a reading.

## Status bits

The bits saying a reading cannot be trusted or is not final become
`device_issues`, and `DeviceStatusValidator` rejects the reading (ADR-0005).
Questionable readings are rejected, not published with a lower status. An absent
status field means no issues, as before.

**Measurement Status** (PLXS 1.0.1 Table 3.4)

| Bit | Definition | Handling |
|-----|------------|----------|
| 0–4 | Reserved for Future Use | Ignored |
| 5 | Measurement Ongoing | Rejected (not final) |
| 6 | Early Estimated Data | Rejected (not final) |
| 7 | Validated Data | Accepted |
| 8 | Fully Qualified Data | Accepted |
| 9 | Data from Measurement Storage | Rejected: a continuous measurement has no timestamp, so a stored one would be stamped with the wrong time |
| 10 | Data for Demonstration | Rejected (not a real measurement) |
| 11 | Data for Testing | Rejected (not a real measurement) |
| 12 | Calibration Ongoing | Rejected |
| 13 | Measurement Unavailable | Rejected |
| 14 | Questionable Measurement Detected | Rejected |
| 15 | Invalid Measurement Detected | Rejected |

**Device and Sensor Status** (PLXS 1.0.1 Table 3.5)

| Bit | Definition | Handling |
|-----|------------|----------|
| 0 | Extended Display Update Ongoing | Accepted (says nothing about the reading) |
| 1 | Equipment Malfunction Detected | Rejected |
| 2 | Signal Processing Irregularity Detected | Rejected |
| 3 | Inadequate Signal Detected | Rejected |
| 4 | Poor Signal Detected | Rejected |
| 5 | Low Perfusion Detected | Rejected |
| 6 | Erratic Signal Detected | Rejected |
| 7 | Non-Pulsatile Signal Detected | Rejected |
| 8 | Questionable Pulse Detected | Rejected |
| 9 | Signal Analysis Ongoing | Rejected (not final) |
| 10 | Sensor Interference Detected | Rejected |
| 11 | Sensor Unconnected to User | Rejected |
| 12 | Unknown Sensor Connected | Rejected |
| 13 | Sensor Displaced | Rejected |
| 14 | Sensor Malfunctioning | Rejected |
| 15 | Sensor Disconnected | Rejected |
| 16–23 | Reserved for Future Use | Ignored |

## No timestamp — effective is processing time

Unlike the Blood Pressure Measurement characteristic, the PLX **Continuous
Measurement** characteristic (`0x2A5F`) carries **no timestamp** field. A
continuous SpO2 reading is therefore stamped with the processing time
(`effective = now()`), timezone-aware. The clock is injectable so tests can pin
it. This slice introduces no device-timestamp handling and no store-and-forward
path, and so inherits none of the timezone assumptions documented for blood
pressure.

## Spot-check measurement deferred

The PLX **Spot-Check Measurement** characteristic (`0x2A5E`) is delivered via
GATT indications and carries an embedded timestamp. It is **deferred** to a
later slice and is not implemented here; this slice acquires only the Continuous
Measurement stream over notifications. If spot-check acquisition is added later,
its zoneless timestamp handling should reuse the blood-pressure convention
documented in `docs/protocol-blood-pressure-measurement.md`.

## Trademark notice

Bluetooth® is a registered trademark of Bluetooth SIG, Inc. This project is not
affiliated with or endorsed by Bluetooth SIG. Bluetooth terminology is used here
only to describe compatibility with published specifications.
