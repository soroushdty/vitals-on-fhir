# Design Document

**Spec: oxygen-saturation** (pulse oximetry — second phase-2 slice)

## Overview

This design implements SpO2 acquisition end to end by **reusing** the machinery the blood-pressure
slice put in place. Oxygen saturation is a single scalar percentage, so it lands as a new
`ScalarVital` (`OxygenSaturation`) — which means the existing `ScalarVitalMapper` produces its
Observation with no new mapper code, exactly as `HeartRate` does. The only genuinely new logic is a
PLX Continuous Measurement parser; and even its hardest part (IEEE-11073 SFLOAT decoding) already
exists in the blood-pressure parser and is lifted into a shared pure-function module.

Grounded in the current code (read during design): `vitals/base.py`, `vitals/builtin/heart_rate.py`,
`adapters/ble.py` (the reusable `BleConnection`), `adapters/parser.py`, `adapters/bp_parser.py`,
`adapters/builtin/{mock,blood_pressure_ble}.py`, `fhir/mappers.py`, `fhir/__init__.py`,
`validation/builtin/validators.py`, `config.py`, and `cli.py`. Traceability: each section cites the
FR-SPO2-\*/NFR-SPO2-\* it satisfies. The existing heart-rate and blood-pressure suites are the
regression guardrail through the two refactors (SFLOAT consolidation, validator generalization).

### What is reused unchanged (the payoff of BP going first)

- **`BleConnection`** (`adapters/ble.py`) — the profile-agnostic scan/connect/subscribe/reconnect
  lifecycle. The SpO2 adapter composes it with PLX UUIDs, exactly as `BloodPressureBleAdapter` does.
  No change to `BleConnection`.
- **`ScalarVitalMapper`** (`fhir/mappers.py`) — builds an Observation from a `ScalarVital`'s class
  metadata. `OxygenSaturation` resolves to it via the existing MRO registry. No new mapper code.
- **`DuplicateValidator`** — its scalar identity key `(device_id, effective, value)` already covers
  `OxygenSaturation`. No change.
- **`SensorContactValidator`** — reads `getattr(vital, "sensor_contact", None)`, so it passes SpO2
  (which has no such field) through unchanged. No change.

### What is new or changed

| Area | Change | Requirement |
|------|--------|-------------|
| `vitals/builtin/oxygen_saturation.py` | new `OxygenSaturation(ScalarVital)` | FR-SPO2-1 |
| `adapters/sfloat.py` | **new** shared SFLOAT pure-function module | FR-SPO2-2 |
| `adapters/bp_parser.py` | delegate SFLOAT decode to the shared module (behavior-preserving) | FR-SPO2-2 |
| `adapters/plx_parser.py` | new `PlxContinuousMeasurementParser` | FR-SPO2-3 |
| `adapters/builtin/pulse_oximeter_ble.py` | new `PulseOximeterBleAdapter` (composes `BleConnection`) | FR-SPO2-4 |
| `adapters/builtin/mock.py` | new `MockOximeterAdapter` + `OximeterEmissionMode` | FR-SPO2-8 |
| `validation/builtin/validators.py` | generalize `PlausibleRangeValidator` to per-class bounds | FR-SPO2-6 |
| `config.py` + `.env.example` | `VOF_SPO2_MIN` / `VOF_SPO2_MAX` | FR-SPO2-6 |
| `cli.py` | short names `spo2` / `mock-spo2`; wire SpO2 bounds | FR-SPO2-8, FR-SPO2-6 |
| `fhir/builders.py` | CapabilityStatement note (search unchanged) | FR-SPO2-7 |
| `docs/protocol-pulse-oximeter-measurement.md` | Bluetooth SIG citation | FR-SPO2-3, NFR-SPO2-4 |

Dependency directions are unchanged; every new module lives in the package that already owns its
concern, so `test_dependency_directions.py` stays green (NFR-SPO2-2).

---

## Components and Interfaces

### 1. `OxygenSaturation` — `vitals/builtin/oxygen_saturation.py` (FR-SPO2-1)

A frozen `ScalarVital`, structurally identical to `HeartRate` but for SpO2. No new instance fields
(SpO2 has no sensor-contact concept in this slice):

```python
@dataclass(frozen=True, kw_only=True)
class OxygenSaturation(ScalarVital):
    loinc_code: ClassVar[str] = "59408-5"   # Oxygen saturation in Arterial blood by Pulse oximetry
    ucum_unit: ClassVar[str] = "%"
    us_core_profile: ClassVar[str] = (
        "http://hl7.org/fhir/us/core/StructureDefinition/us-core-pulse-oximetry"
    )
    plausible_range: ClassVar[tuple[float, float]] = (70.0, 100.0)
```

Exported from `vitals/__init__.py` under `# Concrete defaults`. The existing `ScalarVital`
`__init_subclass__` enforcement fires because `loinc_code` is assigned, so missing metadata raises at
import time (FR-SPO2-1). No FHIR code in this package (NFR-SPO2-3).

**Range rationale.** Default `(70, 100)`: 100% is the physical ceiling; 70% is a wide lower plausibility
bound (readings below are clinically severe and often artifact). These are plausibility bounds, not
diagnostic thresholds, and are overridable via `VOF_SPO2_*` (FR-SPO2-6).

**LOINC choice.** `59408-5` ("Oxygen saturation in Arterial blood by Pulse oximetry") is the code the
US Core Pulse Oximetry profile is built around. The profile also permits optional inhaled-oxygen
components, but a standalone home oximeter over PLX reports only SpO2, so a scalar panel value with no
components is a conformant instance for this device class. This is why SpO2 is a `ScalarVital`, not a
`ComponentVital` — recorded so it is not re-litigated.

### 2. Shared SFLOAT decoding — `adapters/sfloat.py` (FR-SPO2-2)

Today `decode_sfloat` and the reserved-mantissa set live privately inside `adapters/bp_parser.py`.
Both the BP parser and the new PLX parser need identical IEEE-11073 SFLOAT decoding, so it is lifted
into a small pure-function module:

```python
# adapters/sfloat.py
_SFLOAT_SIZE = 2
_SFLOAT_RESERVED_MANTISSAS = frozenset({0x07FF, 0x0800, 0x07FE, 0x0802, 0x0801})

def decode_sfloat(data: bytes, offset: int) -> float | None:
    """Decode a 16-bit IEEE-11073 SFLOAT at *offset* (little-endian).

    Returns None for reserved mantissa values (NaN, NRes, ±INFINITY, reserved),
    which do not represent a usable number.
    """
    ...  # identical logic to today's bp_parser.decode_sfloat
```

- **Placement:** `adapters/` (both parsers live there). Depends only on the standard library — no new
  cross-package import (NFR-SPO2-2).
- **BP parser refactor (behavior-preserving):** `bp_parser.py` imports `decode_sfloat` and the
  reserved set from `adapters.sfloat` instead of defining them. `SFLOAT`-related BP tests stay green;
  if any BP behavior changes, the extraction is wrong (FR-SPO2-2 guardrail).
- **`SFLOAT_SIZE`** is exported too, so both parsers compute offsets from one constant.
- **Provenance:** the module header cites IEEE-11073-20601; the new protocol doc references it, and the
  existing BP protocol doc already cites the same standard.

This is the one shared-code decision in the spec. Alternative considered — duplicating the function
into the PLX parser — rejected: two copies of a fiddly bit-twiddling function drift; DRY here has no
downside because both callers are in the same package and the logic is pure.

### 3. `PlxContinuousMeasurementParser` — `adapters/plx_parser.py` (FR-SPO2-3)

Decodes GATT `0x2A5F` (PLX Continuous Measurement). Byte-level logic in pure functions the class
delegates to, mirroring `parser.py` and `bp_parser.py`.

**Payload layout (PLX Continuous Measurement).** Flags byte (offset 0), then the mandatory
**SpO2–PR normal** pair: SpO2 SFLOAT (offset 1) and pulse-rate SFLOAT (offset 3). Optional fields
follow, gated by the flags:

- bit 0 — SpO2PR-Fast field present (an extra SFLOAT pair)
- bit 1 — SpO2PR-Slow field present (an extra SFLOAT pair)
- bit 2 — Measurement Status field present (2 bytes)
- bit 3 — Device and Sensor Status field present (3 bytes)
- bit 4 — Pulse Amplitude Index field present (2 bytes SFLOAT)

Pure functions:

```python
def parse_plx_flags(byte: int) -> PlxFlags        # decode the five relevant bits
def required_length(flags: PlxFlags) -> int       # 1 + 2 SFLOATs(4) + optional fields per flags
# SpO2 SFLOAT is decoded via adapters.sfloat.decode_sfloat(data, _SPO2_OFFSET=1)
```

`PlxContinuousMeasurementParser(GattCharacteristicParser)`:

```python
def __init__(self, device_id: str, now: Callable[[], datetime] | None = None): ...
    # now defaults to lambda: datetime.now(UTC)  (tz-aware), injectable for tests

def parse(self, data: bytes) -> VitalSign | None:
    if len(data) < 1: return None
    flags = parse_plx_flags(data[0])
    if len(data) < required_length(flags): return None
    spo2 = decode_sfloat(data, _SPO2_OFFSET)          # shared decoder
    if spo2 is None: return None                       # reserved/unusable → drop
    return OxygenSaturation(
        effective=self._now(),                         # no timestamp in continuous char.
        device_id=self._device_id,
        value=spo2,
    )
```

- The pulse-rate SFLOAT and optional fields are **length-accounted but not decoded into the Reading**
  (FR-SPO2-3; pulse rate out of scope).
- No unit normalization: SpO2 is a dimensionless percentage in the PLX encoding; the SFLOAT already
  yields the percentage value.
- `effective = now()` (tz-aware) because the Continuous characteristic carries no timestamp
  (FR-SPO2-3). No store-and-forward here.
- Malformed/short/reserved-SFLOAT → `None`; the adapter drops it, logging at `DEBUG` with byte length
  only, no value (NFR-SPO2-5).
- `docs/protocol-pulse-oximeter-measurement.md` cites the PLX spec and IEEE-11073 SFLOAT (FR-SPO2-3,
  NFR-SPO2-4).

### 4. `PulseOximeterBleAdapter` — `adapters/builtin/pulse_oximeter_ble.py` (FR-SPO2-4)

A near-exact analogue of `BloodPressureBleAdapter`: subclasses `DeviceAdapter` directly, composes a
`BleConnection` configured for the PLX profile, and delegates the lifecycle:

```python
PULSE_OXIMETER_SERVICE_UUID = "00001822-0000-1000-8000-00805f9b34fb"          # 0x1822
PLX_CONTINUOUS_MEASUREMENT_UUID = "00002a5f-0000-1000-8000-00805f9b34fb"      # 0x2A5F

class PulseOximeterBleAdapter(DeviceAdapter):
    supported_vitals = (OxygenSaturation,)
    def __init__(self, *, device_name=None, on_state_change=None, now=None):
        self._now = now
        self._connection = BleConnection(
            service_uuid=PULSE_OXIMETER_SERVICE_UUID,
            characteristic_uuid=PLX_CONTINUOUS_MEASUREMENT_UUID,
            matches=self.matches,
            parser_factory=self._build_parser,
            device_name=device_name,
            on_state_change=on_state_change,
        )
    def matches(self, advertisement) -> bool: return True   # service-UUID scan is authoritative
    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(manufacturer="Generic", model="Pulse Oximeter",
                          identifiers={"profile": "org.bluetooth.service.pulse_oximeter"})
    # state/connect/disconnect/vitals delegate to self._connection
    def _build_parser(self):
        from vitals_on_fhir.adapters.plx_parser import PlxContinuousMeasurementParser
        return PlxContinuousMeasurementParser(
            device_id=self.device_info.identifiers["profile"], now=self._now)
```

`bleak` stays lazily imported inside `BleConnection` only (FR-SPO2-4). The parser import inside
`_build_parser` is lazy to avoid an import cycle (`plx_parser` imports `adapters.ble`), matching the
BP adapter's pattern.

**Indications vs notifications (why `BleConnection` needs no change).** `BleConnection` subscribes via
`client.start_notify(...)`. In `bleak`, `start_notify` transparently enables notifications *or*
indications depending on the characteristic's declared properties, and delivers both through the same
callback. The PLX Continuous Measurement characteristic uses notifications, which is the native fit
for the existing notification queue. So targeting `0x2A5F` requires only passing its UUID — no
lifecycle change. (Spot-check `0x2A5E`, indication-based and carrying a timestamp, is deferred; if
added later it can reuse the same `start_notify` path but will need timestamp handling and is its own
slice — see requirements Out of scope.)

### 5. Per-vital-class plausibility validation — `validation/builtin/validators.py` (FR-SPO2-6)

**The problem.** `PlausibleRangeValidator` today takes a single `(hr_min, hr_max)` at construction and
applies it to *every* `ScalarVital`, falling back to `vital.plausible_range` only when the override is
`None`. With two scalar vitals in the chain (heart rate and SpO2), a single instance carrying HR bounds
would wrongly clamp SpO2 to 20–250, and a second instance carrying SpO2 bounds would wrongly clamp HR
to 70–100. The current shape cannot express two different per-class overrides.

**The fix — per-class override map, backward compatible (NFR-SPO2-1).** Generalize the validator to
accept an optional `overrides: dict[type, tuple[float, float]]` mapping a vital class to its
`(min, max)`. Lookup order per reading: `overrides[type(vital)]` if present, else
`vital.plausible_range`. The legacy `(hr_min, hr_max)` constructor form is **retained** and internally
translated to `{HeartRate: (hr_min, hr_max)}` so existing construction and tests keep working:

```python
class PlausibleRangeValidator(Validator):
    name = "plausible_range"
    def __init__(
        self,
        hr_min: float | None = None,
        hr_max: float | None = None,
        *,
        overrides: dict[type, tuple[float, float]] | None = None,
    ) -> None:
        self._overrides: dict[type, tuple[float, float]] = dict(overrides or {})
        # Back-compat: a bare (hr_min, hr_max) maps to a HeartRate override.
        if hr_min is not None and hr_max is not None:
            from vitals_on_fhir.vitals.builtin.heart_rate import HeartRate
            self._overrides.setdefault(HeartRate, (hr_min, hr_max))

    def check(self, vital):
        if not isinstance(vital, ScalarVital):
            return accepted
        low, high = self._overrides.get(type(vital), vital.plausible_range)
        if low <= vital.value <= high: return accepted
        return rejected(reason=f"value outside plausible range [{low}, {high}]")  # no value name-only
```

Notes:
- The `HeartRate` import is inside `__init__` (lazy) to keep `validation` free of a hard module-level
  dependency on a specific builtin vital and to preserve the package's minimal import surface; it does
  not change dependency direction (`validation` may import `vitals`).
- Rejection reason still names only the bounds, never the value (NFR-SPO2-5). Behavior for a lone
  `(hr_min, hr_max)` construction is identical to today, so existing tests pass unchanged
  (NFR-SPO2-6 guardrail).
- Alternative considered — a second `PlausibleRangeValidator` instance in the chain keyed by type —
  rejected: two instances of the same-named validator muddy rejection provenance and each would still
  need per-class dispatch to avoid clamping the wrong vital. One map-driven instance is clearer.

**Duplicate + sensor-contact validators unchanged** (FR-SPO2-6): `DuplicateValidator`'s scalar key
covers SpO2; `SensorContactValidator` passes it through.

### 6. FHIR mapping — reused, no code (FR-SPO2-5)

`OxygenSaturation` is a `ScalarVital`, and `fhir/__init__.py` already registers
`ScalarVitalMapper` for `ScalarVital`. `resolve_mapper(OxygenSaturation)` walks the MRO and returns
`ScalarVitalMapper`, which builds the Observation from `OxygenSaturation`'s class metadata:
panel `code` `59408-5`, `valueQuantity` with UCUM `code` `%`, `meta.profile` the US Core Pulse
Oximetry URL. No registration, no mapper subclass, no change to `fhir/`.

**One display-string caveat.** `ScalarVitalMapper` sets `valueQuantity.unit` to the module constant
`_VALUE_UNIT_DISPLAY = "beats/minute"` (an HR-specific human label) while `code` is the authoritative
UCUM `ucum_unit`. For SpO2 the authoritative `code` is correctly `%`, but the human `unit` display
would read "beats/minute", which is wrong for SpO2. **Design decision:** change `ScalarVitalMapper` to
use the vital's `ucum_unit` as the `unit` display (i.e. drop the HR-specific `_VALUE_UNIT_DISPLAY`
constant, or use `ucum_unit` when no per-class display is known). This is a small, correctness-driven
change; HR Observations then show `unit: "/min"` instead of `"beats/minute"`. Because `unit` is a
display string and `code` remains authoritative, this is not a semantic/interoperability change, but
it **does alter HR Observation output**, so:
- the existing HR mapper test that asserts `"beats/minute"` must be updated, and
- a `CHANGELOG.md` bullet notes the HR `valueQuantity.unit` display changed from `"beats/minute"` to
  `"/min"` (non-breaking; `code` unchanged).

This is called out here rather than buried in tasks because it touches an existing, tested output. If
the team prefers to preserve `"beats/minute"` for HR, the alternative is a per-class display map in the
mapper; that is more machinery for a display string, so the simpler `ucum_unit`-as-display is proposed.
Confirm during review.

### 7. Configuration — `config.py` + `.env.example` (FR-SPO2-6)

```python
# Validation bounds — oxygen saturation (%)
spo2_min: float = 70.0
spo2_max: float = 100.0
```

`env_prefix="VOF_"` maps these to `VOF_SPO2_MIN` / `VOF_SPO2_MAX`; `extra="forbid"` still rejects
unknown vars. Both added to `.env.example` with comments. Surface after this slice: the `VOF_*` count
grows by two (see the checkpoint update in `docs/brief-config-file.md`).

### 8. CLI wiring — `cli.py` (FR-SPO2-8, FR-SPO2-6)

- `_resolve_adapter`: add `"spo2"` → `PulseOximeterBleAdapter(device_name=...)` and `"mock-spo2"` →
  `MockOximeterAdapter()`, alongside the existing names. Update the `--adapter` help text and the
  `ValueError`/`argparse` strings to list the new names.
- `_build_orchestrator`: construct the `PlausibleRangeValidator` with an explicit overrides map so both
  scalar vitals get correct bounds:
  ```python
  scalar_overrides = {
      HeartRate: (settings.hr_min, settings.hr_max),
      OxygenSaturation: (settings.spo2_min, settings.spo2_max),
  }
  chain = ValidatorChain([
      PlausibleRangeValidator(overrides=scalar_overrides),
      SensorContactValidator(),
      ComponentRangeValidator(bp_overrides),
      DuplicateValidator(),
  ])
  ```
  This replaces the current `PlausibleRangeValidator(settings.hr_min, settings.hr_max)` construction.
  Order is unchanged; each validator no-ops for vitals it doesn't handle.
- No orchestrator change: `orchestrator.run()` already resolves the mapper per-vital via
  `resolve_mapper`, so `OxygenSaturation → ScalarVitalMapper` dispatches automatically.

### 9. Mock pulse-oximeter source — `adapters/builtin/mock.py` (FR-SPO2-8)

Add a parallel `MockOximeterAdapter` + `OximeterEmissionMode`, mirroring `MockAdapter` and
`MockBloodPressureAdapter`, emitting `OxygenSaturation`, never importing `bleak`:

```python
class OximeterEmissionMode(enum.Enum):
    VALID = "valid"              # e.g. 98%
    IMPLAUSIBLE = "implausible"  # below the plausible lower bound (e.g. 50%)

class MockOximeterAdapter(DeviceAdapter):
    supported_vitals = (OxygenSaturation,)
    # connect/disconnect/state mirror MockAdapter; vitals() yields OxygenSaturation
```

There is no store-and-forward mode (the continuous characteristic carries no timestamp; that path is a
BP concern). Exported from `adapters/__init__.py` under `# Concrete defaults`.

---

## Data Models

`OxygenSaturation` (frozen, kw_only): `effective: datetime` (tz-aware, inherited), `device_id: str`
(inherited), `value: float` (inherited from `ScalarVital`, the SpO2 percentage). Class metadata:
`loinc_code` `59408-5`, `ucum_unit` `%`, `us_core_profile` US Core Pulse Oximetry, `plausible_range`
`(70.0, 100.0)`.

Produced FHIR `Observation` (US Core Pulse Oximetry) — shape:

```jsonc
{
  "resourceType": "Observation",
  "id": "<uuid4>",
  "meta": {"profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-pulse-oximetry"]},
  "status": "final",
  "category": [{"coding": [{"system": ".../observation-category", "code": "vital-signs", ...}]}],
  "code": {"coding": [{"system": "http://loinc.org", "code": "59408-5"}]},
  "subject": {"reference": "Patient/local-patient"},
  "device":  {"reference": "Device/<slug>"},
  "effectiveDateTime": "2026-09-23T12:00:00+00:00",
  "issued":            "2026-09-23T12:00:00+00:00",
  "valueQuantity": {"value": 98, "unit": "%", "system": "http://unitsofmeasure.org", "code": "%"}
}
```

---

## Error Handling

- **Malformed / unusable payload** (short, reserved SFLOAT): parser returns `None`; adapter drops it,
  logs at `DEBUG` with byte length only, no value. (FR-SPO2-3, NFR-SPO2-5)
- **Out-of-range SpO2**: `PlausibleRangeValidator` rejects; orchestrator logs at `INFO` with the bounds
  but not the value. (FR-SPO2-6, NFR-SPO2-5)
- **Observation construction failure**: `Observation.model_validate` raises; orchestrator boundary
  catches, logs at `ERROR` (no values), does not store/serve. (FR-SPO2-5)
- **`bleak` unavailable**: `BleConnection` raises a clear `RuntimeError` via the existing lazy-import
  guard. The mock SpO2 path needs no Bluetooth stack. (FR-SPO2-4)

---

## Testing Strategy

Fast suite, no hardware (NFR-SPO2-6). New tests mirror the `tests/` structure:

- `vitals/`: `OxygenSaturation.__init_subclass__` metadata enforcement (a deliberately incomplete local
  subclass raises); instances are frozen; class metadata present and correct.
- `adapters/`: `sfloat` decode tests including reserved NaN/NRes/±INF values → `None` and a Hypothesis
  round-trip where practical; `plx_parser` pure-function tests (`parse_plx_flags`, `required_length`
  across optional-field combinations); `parse()` for well-formed SpO2, optional fields present
  (length accounting), and short/reserved → `None`. `MockOximeterAdapter` emission modes.
- `adapters/` contract: `PulseOximeterBleAdapter` satisfies the `DeviceAdapter` contract suite and the
  `BleConnection` behavior (state transitions, drop-None, disconnect unblocks `vitals()`, quiet
  interval while connected is not a disconnection).
- `fhir/`: `resolve_mapper(OxygenSaturation) → ScalarVitalMapper`; the built Observation validates as
  US Core Pulse Oximetry with `value`, UCUM `code` `%`, LOINC `59408-5`. Existing
  `HeartRate → ScalarVitalMapper` and `BloodPressure → ComponentVitalMapper` resolution unchanged.
- `validation/`: SpO2 override applies to SpO2 and not to HR; HR override applies to HR and not to
  SpO2 (the cross-application guard, FR-SPO2-6); back-compat `(hr_min, hr_max)` construction behaves
  as before; rejection reason names bounds only.
- `config/`: `VOF_SPO2_*` load and defaults; `extra="forbid"` still rejects unknown vars.
- **Regression guardrail:** the full existing heart-rate and blood-pressure suites plus
  `test_dependency_directions.py` stay green after the SFLOAT consolidation and the
  `PlausibleRangeValidator` generalization (NFR-SPO2-1, NFR-SPO2-2, NFR-SPO2-6). The HR mapper test
  that asserts the `valueQuantity.unit` display is updated to `"/min"` (see design §6).
- Hardware tests for a real oximeter carry the `hardware` marker, excluded from CI.

---

## Resolved decisions

1. **Scalar, not component.** SpO2 is a single percentage → `ScalarVital`; the existing scalar mapper
   builds its Observation with no new code. (design §1, §6)
2. **Continuous characteristic only.** Target `0x2A5F` (notify-based), which fits `BleConnection`
   unchanged. Spot-check `0x2A5E` (indication + timestamp) is deferred to its own slice. (design §4)
3. **Shared SFLOAT.** Lift `decode_sfloat` into `adapters/sfloat.py`; the BP parser delegates to it
   (behavior-preserving). (design §2)
4. **Per-class plausibility.** Generalize `PlausibleRangeValidator` to a per-vital-class overrides map,
   backward compatible with the `(hr_min, hr_max)` form. (design §5)
5. **HR unit display.** `ScalarVitalMapper` uses `ucum_unit` as the `valueQuantity.unit` display so
   SpO2 reads `%`; this changes HR's display from `"beats/minute"` to `"/min"` (non-breaking, `code`
   unchanged). Flagged for review in design §6.
6. **Adapter short names.** `"spo2"` (built-in BLE) and `"mock-spo2"` (mock). (design §8)
