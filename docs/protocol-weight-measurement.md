# Protocol source citation — Bluetooth Weight Measurement (0x2A9D)

This document records the Bluetooth SIG specifications used to implement
`WeightMeasurementParser` (`src/vitals_on_fhir/adapters/weight_parser.py`) and
the body-weight BLE acquisition path (`src/vitals_on_fhir/adapters/ble.py`, via
the reusable `BleConnection` lifecycle, composed by `WeightScaleBleAdapter`).
Unlike the blood-pressure, pulse-oximeter, and temperature parsers, the weight
value is **not** an IEEE-11073 SFLOAT/FLOAT — it is a plain little-endian uint16
whose physical resolution depends on the flags byte — so this parser adds a
dedicated unit-scaling function and does not use
`src/vitals_on_fhir/adapters/sfloat.py`. The 7-byte org.bluetooth date-time
decoding is shared with the blood-pressure and temperature parsers through
`src/vitals_on_fhir/adapters/datetime_field.py` (`decode_timestamp`).

Satisfies requirements **FR-WT-3**, **FR-WT-1**, **FR-WT-8**, and **NFR-WT-4**,
and the protocol-sourcing rules in `.kiro/steering/security-privacy.md`: BLE
characteristic formats and GATT service UUIDs come only from published Bluetooth
SIG specifications, cited here with specification name, version, and URL or
publication date.

All protocol knowledge in the parser (flags byte, the uint16 weight value, the SI
vs Imperial resolution and the pound→kilogram normalization, the optional
timestamp, user-ID, and BMI-and-height fields, and field offsets) derives from
these published specifications. No code was copied, translated, or closely
paraphrased from other projects or vendor SDKs.

## Cited specifications

| Specification | What it defines | Version | Reference |
|---------------|-----------------|---------|-----------|
| Weight Scale Service (WSS) | The Weight Scale Service (`0x181D`) and its Weight Measurement characteristic (`0x2A9D`) | 1.0 (adopted 2014-11-25) | <https://www.bluetooth.com/specifications/specs/weight-scale-service-1-0/> |
| Weight Scale Profile (WSP) | The profile that uses the Weight Scale Service, including the Collector/Sensor roles | 1.0 (adopted 2014-11-25) | <https://www.bluetooth.com/specifications/specs/weight-scale-profile-1-0/> |
| GATT Specification Supplement (GSS) | Field structure of the Weight Measurement characteristic: flags byte, the uint16 weight value, the unit flag and its per-unit resolution, and the optional timestamp, user-ID, and BMI-and-height fields, with their offsets | Current published revision | <https://www.bluetooth.com/specifications/specs/gatt-specification-supplement/> |
| Assigned Numbers | UUID assignments for the Weight Scale Service (`0x181D`) and the Weight Measurement characteristic (`0x2A9D`) | Current published revision | <https://www.bluetooth.com/specifications/assigned-numbers/> |

## How the specifications map to the parser

The Weight Measurement characteristic (`0x2A9D`) payload begins with a flags
byte, followed by a mandatory uint16 weight value (offset 1), then optional
fields. The parser decodes each field per the GATT Specification Supplement:

- **Bit 0 — Measurement Units**: `0` = SI, the raw uint16 is weight in units of
  `0.005` kg; `1` = Imperial, the raw uint16 is weight in units of `0.01` lb. The
  two per-unit resolutions differ, so the parser selects the resolution from the
  flags byte (never inferred from the value) and, in the Imperial case, converts
  pounds to kilograms with the exact factor `0.45359237`. The constructed
  `BodyWeight` therefore always carries kilograms (UCUM `kg`).
- **Bit 1 — Timestamp present**: when set, a 7-byte org.bluetooth date-time field
  follows the weight value. The parser uses it as the reading's measurement
  (`effective`) time, enabling store-and-forward. When absent, the parser stamps
  the reading with the processing time (an injectable, timezone-aware local
  clock).
- **Bit 2 — User ID present**: when set, a 1-byte user-ID field follows the
  weight and the optional timestamp. It is decoded **only to compare** with
  `VOF_DEVICE_USER_ID` and is **never logged or stored** (see the privacy note
  below).
- **Bit 3 — BMI and Height present**: when set, a BMI uint16 and a height uint16
  (4 bytes total) follow. They are accounted for when computing the minimum
  payload length, but are not decoded into the reading.

Payloads too short for the fields their flags byte declares, or carrying an
invalid calendar date-time when the timestamp flag is set, are rejected (`parse`
returns `None`) so the adapter drops them without yielding a reading.

## SI vs Imperial scaling — a decode trap

The weight value is a plain uint16, but its meaning depends on the unit flag, and
the SI and Imperial resolutions are **not** related by a simple after-the-fact
unit conversion: SI is `0.005` kg per raw unit while Imperial is `0.01` lb per raw
unit. Decoding an SI payload with the Imperial resolution (or vice versa) yields a
weight wrong by roughly a factor of two, which is close enough to look plausible
and therefore dangerous. The parser guards against this by selecting the
resolution from the flags byte and folding the pound→kilogram conversion into the
same pure scaling step, so a caller cannot split or mis-order the two.

*(Protocol facts rephrased for compliance with licensing restrictions; the sources
are paraphrased and linked inline above.)*

## Timezone assumption

The org.bluetooth date-time field carries no timezone. As with blood pressure and
temperature, a decoded device timestamp is interpreted as the **host's local
time** and returned timezone-aware with the host's local offset. This is a
documented limitation and follows the same convention as the blood-pressure
parser; see `docs/protocol-blood-pressure-measurement.md` for the full rationale
and the shared `decode_timestamp` helper.

## Privacy note — the optional user-ID field

The Weight Measurement characteristic can carry a device-assigned user ID (flags
bit 2), which multi-user scales use to route a reading to a stored profile; `0xFF`
means "unknown user" (a guest). This project records one Patient, so it must not
file another household member's weight under that Patient (#8, ADR-0004).

The parser decodes the user ID only to compare it with `VOF_DEVICE_USER_ID`, and
keeps the outcome (`device_user`) on the reading, never the ID. `DeviceUserValidator`
rejects readings from other users or the unknown user, and every reading from a
multi-user scale while the setting is unset. The ID is never logged, stored, or put
into FHIR, so no per-user identifier enters the pipeline. This is consistent with
the security and privacy rules in `.kiro/steering/security-privacy.md`.

## Range rationale — the `(2.0, 650.0)` kg plausibility bounds

The default plausibility range for `BodyWeight` is `(2.0, 650.0)` kg. These are
**physical-plausibility bounds, not clinical thresholds.** Their only job is to
reject values that could not have come from a real human on a home scale — a
zero/empty-scale decode artifact, a wrong-unit misread, or a scale returning
garbage before the reading stabilizes — not to judge whether a weight is
clinically low or high for any particular person. They are overridable via
`VOF_WEIGHT_MIN` / `VOF_WEIGHT_MAX`.

- **Lower bound `2.0` kg** sits below the low end of realistic standing-scale
  readings while rejecting a `0`/near-zero decode artifact or an empty-scale value.
  (Extremely-low-birth-weight infants weigh well under 1 kg, but a consumer
  standing body-weight scale is not used on neonates, so the floor need not extend
  that low.)
- **Upper bound `650.0` kg** sits just above the heaviest human body weights ever
  documented; the heaviest recorded human weight is around `635` kg
  (<https://www.guinnessworldrecords.com/world-records/heaviest-man>;
  see also <https://en.wikipedia.org/wiki/Jon_Brower_Minnoch>). Placing the ceiling
  a little above the highest documented value keeps every plausible real weight in
  range while rejecting non-physiological high values as artifacts.

Content was rephrased for compliance with licensing restrictions; the sources are
paraphrased and linked inline above.

## Trademark notice

Bluetooth® is a registered trademark of Bluetooth SIG, Inc. This project is not
affiliated with or endorsed by Bluetooth SIG. Bluetooth terminology is used here
only to describe compatibility with published specifications.
