# Design Document

**Spec: home-health-devices** (blood pressure — first phase-2 slice)

## Overview

This design implements blood-pressure acquisition end to end, reusing the heart-rate pipeline's
architecture. It fleshes out the `ComponentVital` ABC (empty stub today), adds `BloodPressure` as
the first concrete `ComponentVital`, activates `ComponentVitalMapper`, extracts the profile-agnostic
BLE lifecycle into a reusable unit used by composition, adds a `BloodPressureMeasurementParser`
(GATT `0x2A35`, IEEE-11073 SFLOAT decoding), a component-aware validator, config, a mock
blood-pressure source, and the protocol citation in `docs/`.

It is grounded in the current code (read during design): `vitals/base.py`, `adapters/ble.py`,
`fhir/base.py`, `fhir/mappers.py`, `fhir/__init__.py`, `validation/builtin/validators.py`,
`adapters/builtin/{mock,miband10}.py`, and `config.py`. Traceability: each section cites the
FR-HH-*/NFR-HH-* it satisfies. The `hr-pipeline` tests are the regression guardrail — they must
stay green through the BLE extraction.

### Design principles carried from requirements review

- **Option A component model** — component *structure* is class metadata; component *values* are
  named typed instance fields. Keeps `vitals/` FHIR-free and target-neutral (NFR-HH-3).
- **Composition for the BLE lifecycle** — no new inheritance level; preserve `BleHeartRateAdapter`'s
  public surface (NFR-HH-1, 3-level cap).
- **No MAP** — systolic + diastolic only; additive later.
- **Device-rate "continuous"; liveness from connection state** — no new logic; documented behavior.

---

## Architecture

The pipeline shape is unchanged (adapter → validators → mapper → sinks). New/changed pieces:

```
vitals/
  base.py           ComponentVital gets concrete shape + ComponentSpec  [FR-HH-1]
  builtin/
    blood_pressure.py   BloodPressure(ComponentVital)                   [FR-HH-2]
adapters/
  ble.py            extract BleConnection (lifecycle) via composition;  [FR-HH-4]
                    BleHeartRateAdapter delegates to it (surface kept)
  bp_parser.py      BloodPressureMeasurementParser + pure SFLOAT/decode  [FR-HH-5]
  builtin/
    blood_pressure_ble.py  BloodPressureBleAdapter (uses BleConnection)  [FR-HH-4]
    mock.py          MockBloodPressureAdapter (new class, no bleak)      [FR-HH-9]
validation/
  builtin/validators.py  ComponentRangeValidator; DuplicateValidator     [FR-HH-7]
                         generalized to components (identity key)
fhir/
  mappers.py        implement ComponentVitalMapper.to_observation        [FR-HH-3]
  __init__.py       register ComponentVitalMapper for ComponentVital     [FR-HH-3]
  builders.py       CapabilityStatement note (search unchanged)          [FR-HH-8]
config.py           VOF_BP_* range settings                              [FR-HH-7]
cli.py              adapter short name; wire ComponentRangeValidator      [FR-HH-9]
docs/
  protocol-blood-pressure-measurement.md   Bluetooth SIG citation        [FR-HH-5, NFR-HH-4]
```

Dependency directions are unchanged; every new module lives in the package that already owns its
concern, so `test_dependency_directions.py` stays green (NFR-HH-2).

---

## Components and Interfaces

### 1. `ComponentVital` concrete shape — `vitals/base.py` (FR-HH-1)

Today `ComponentVital` is an empty `VitalSign` subclass. We give it a component structure using a
frozen `ComponentSpec` value object, declared as class metadata, with values held in named instance
fields on the concrete subclass.

```python
@dataclass(frozen=True)
class ComponentSpec:
    """Binds one component of a ComponentVital to its vocabulary and value field."""
    field_name: str   # name of the instance attribute holding the value
    loinc_code: str   # component LOINC (e.g. "8480-6" systolic)
    ucum_unit: str    # component UCUM unit (e.g. "mm[Hg]")


@dataclass(frozen=True, kw_only=True)
class ComponentVital(VitalSign):
    """Abstract base for multi-component vital signs (e.g. blood pressure).

    A concrete subclass declares:
      - ``loinc_code``     : the panel LOINC code (inherited ClassVar)
      - ``us_core_profile``: the panel US Core profile (inherited ClassVar)
      - ``components``     : an ordered tuple of ComponentSpec (this ClassVar)
    and one instance field per ComponentSpec.field_name carrying that value.
    """
    components: ClassVar[tuple[ComponentSpec, ...]]

    def component_values(self) -> tuple[tuple[ComponentSpec, float], ...]:
        """Return (spec, value) pairs in declared order, reading named fields.

        The single point the mapper and validator use; keeps them free of any
        per-vital special-casing.
        """
        return tuple((spec, float(getattr(self, spec.field_name))) for spec in self.components)
```

**Metadata enforcement.** The existing `__init_subclass__`/`_check_class_vars` in `VitalSign` only
fires when `loinc_code` is in `cls.__dict__`. `BloodPressure` sets `loinc_code`, so it fires — we
extend `_check_class_vars` (or add a `ComponentVital.__init_subclass__`) to also require, for a
concrete `ComponentVital`, that `components` is declared and non-empty, and that every
`spec.field_name` is an actual field on the class. Rationale: fail at import time (FR-HH-1), the
same discipline `ScalarVital` gets.

**Why named fields, not a dict** (Option A, from review): strong typing (mypy sees `systolic`),
symmetry with `ScalarVital`, and neutral LOINC/UCUM bindings sit in the domain layer so a future
non-FHIR mapper is a thin loop (NFR-HH-3). `component_values()` is the neutral iteration surface.

### 2. `BloodPressure` — `vitals/builtin/blood_pressure.py` (FR-HH-2)

```python
@dataclass(frozen=True, kw_only=True)
class BloodPressure(ComponentVital):
    loinc_code: ClassVar[str] = "85354-9"                    # BP panel
    us_core_profile: ClassVar[str] = (
        "http://hl7.org/fhir/us/core/StructureDefinition/us-core-blood-pressure"
    )
    components: ClassVar[tuple[ComponentSpec, ...]] = (
        ComponentSpec(field_name="systolic",  loinc_code="8480-6", ucum_unit="mm[Hg]"),
        ComponentSpec(field_name="diastolic", loinc_code="8462-4", ucum_unit="mm[Hg]"),
    )
    systolic: float
    diastolic: float
```

Exported from `vitals/__init__.py` under `# Concrete defaults`. No MAP field (out of scope; additive
later via a third `ComponentSpec`). Frozen, kw_only — consistent with the hierarchy.

Per-component plausible bounds: `ScalarVital` carries `plausible_range`, but `ComponentVital` has no
single value. Two options considered:
- **(a)** put default bounds on each `ComponentSpec` (e.g. `default_range: tuple[float,float]`), or
- **(b)** keep bounds only in the validator/config.

**Decision: (a).** Add `default_range` to `ComponentSpec` so `BloodPressure` declares sane defaults
(systolic 50–250, diastolic 30–150) as domain metadata, mirroring `ScalarVital.plausible_range`. The
validator overrides from config when set. This keeps defaults with the domain object (target-neutral)
rather than hard-coded in the validator.

### 3. BLE lifecycle extraction — `adapters/ble.py` (FR-HH-4, NFR-HH-1)

Today all lifecycle logic lives in `BleHeartRateAdapter` (scan/connect/subscribe, threadsafe queue,
reconnect with capped backoff, disconnect, `_set_state`). We extract it into a **composed helper**,
`BleConnection`, parameterized by what varies: the service UUID, the characteristic UUID, a
`matches` predicate, and a parser factory.

```python
class BleConnection:
    """Profile-agnostic BLE scan/connect/subscribe/reconnect lifecycle.

    Not an ABC and not a DeviceAdapter — a reusable unit that concrete adapters
    hold by composition. Imports ``bleak`` lazily inside methods only.
    """
    def __init__(
        self,
        *,
        service_uuid: str,
        characteristic_uuid: str,
        matches: Callable[[object], bool],
        parser_factory: Callable[[], GattCharacteristicParser],
        device_name: str | None = None,
        on_state_change: Callable[[ConnectionState], Awaitable[None]] | None = None,
    ) -> None: ...

    @property
    def state(self) -> ConnectionState: ...
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    def vitals(self) -> AsyncIterator[VitalSign]: ...   # queue-drain + parse + drop-None
```

`BleHeartRateAdapter` **keeps its exact public surface** (name in `__all__`, abstract `matches`/
`device_info`, constructor `device_name`/`on_state_change`/`now`, `state`/`connect`/`disconnect`/
`vitals`). Internally it now constructs and delegates to a `BleConnection`, passing the HR service/
characteristic UUIDs and a `HeartRateMeasurementParser` factory. `MiBand10Adapter` is untouched.

Inheritance stays at 3 levels: `DeviceAdapter → BleHeartRateAdapter → MiBand10Adapter`, and
`DeviceAdapter → BloodPressureBleAdapter` (the BP adapter subclasses `DeviceAdapter` directly and
composes a `BleConnection`, so its concrete form is 2 levels). `BleConnection` adds no inheritance —
it is held, not inherited (composition; object-model convention).

**Regression safety:** the extraction is behavior-preserving. The 74 existing tests plus
`test_dependency_directions.py` are the guardrail (NFR-HH-6). If any HR test changes behavior, the
extraction is wrong — that's the check.

`GattCharacteristicParser` (already an ABC in `ble.py`) is unchanged and now has a second
implementation.

### 4. `BloodPressureBleAdapter` — `adapters/builtin/blood_pressure_ble.py` (FR-HH-4)

Subclasses `DeviceAdapter` directly, composes a `BleConnection` configured for the BP profile:

```python
class BloodPressureBleAdapter(DeviceAdapter):
    supported_vitals = (BloodPressure,)
    def __init__(self, *, device_name=None, on_state_change=None, now=None): 
        self._conn = BleConnection(
            service_uuid=BLOOD_PRESSURE_SERVICE_UUID,          # 0x1810
            characteristic_uuid=BLOOD_PRESSURE_MEASUREMENT_UUID,# 0x2A35
            matches=self._matches,
            parser_factory=lambda: BloodPressureMeasurementParser(self._device_id(), now),
            device_name=device_name, on_state_change=on_state_change,
        )
    # device_info, state, connect, disconnect, vitals delegate to self._conn / declared here
```

BP cuffs are typically one device with a fixed/known name; a generic name-substring `matches` (like
MiBand10) is sufficient. `device_info` reports manufacturer/model and Bluetooth address once matched.
`bleak` imported lazily inside `BleConnection` only.

### 5. `BloodPressureMeasurementParser` — `adapters/bp_parser.py` (FR-HH-5)

Decodes GATT `0x2A35` per the Bluetooth SIG Blood Pressure Measurement spec. Byte-level logic is
**pure functions** the class delegates to, mirroring `parser.py`:

- `parse_bp_flags(byte) -> BpFlags` — bit 0: unit (0=mmHg, 1=kPa); bit 1: timestamp present;
  bit 2: pulse rate present; bit 3: user id present; bit 4: measurement status present.
- `decode_sfloat(data, offset) -> float | None` — IEEE-11073 16-bit SFLOAT: 4-bit signed exponent,
  12-bit signed mantissa; the special NaN/NRes reserved mantissa values (0x07FF, 0x0800, 0x07FE,
  0x0801, 0x0802) map to "not a usable value". Systolic/diastolic/MAP are three consecutive SFLOATs
  at offsets 1, 3, 5.
- `required_length(flags) -> int` — flags(1) + 3 SFLOATs(6) + optional timestamp(7) + optional
  pulse(2) + optional user-id(1) + optional status(2), summed only for the fields the flags declare.
- `kpa_to_mmhg(value) -> float` — normalize when the unit bit is set (1 kPa = 7.50062 mmHg).
- `decode_timestamp(data, offset) -> datetime` — the 7-byte org.bluetooth date-time (year LE u16,
  month, day, hour, minute, second). The BLE field carries no timezone, so the value is interpreted
  as the **host's local time** and returned timezone-aware with the host's local offset attached
  (e.g. `datetime(...).astimezone()` on a naive-local construction, or building with the local
  `tzinfo`). Rationale: for a single-user home device on the same machine, local time matches what the
  user reads off the cuff. Tradeoff (documented): a reading actually taken in a different zone than the
  host would be mislabeled — acceptable for the local home-monitoring MVP. `now` fallback also uses a
  local-aware timestamp for consistency, still satisfying the tz-aware requirement (FR-HH-6).

`parse(data)`:
1. `len(data) < 1` → `None`.
2. decode flags; `len(data) < required_length(flags)` → `None`.
3. decode systolic (offset 1) and diastolic (offset 3) SFLOATs; if either is a reserved/NaN value →
   `None` (malformed/unusable; drop per FR-HH-5).
4. if unit is kPa, normalize both to mmHg.
5. `effective` = decoded (local-aware) timestamp if the timestamp flag is set, else `now()`
   (local-aware) — store-and-forward, FR-HH-6. Injectable `now` for tests.
6. return `BloodPressure(effective=..., device_id=..., systolic=..., diastolic=...)`.

MAP is decoded for length accounting but intentionally discarded (no MAP field). This is documented
inline and in the requirements. `docs/protocol-blood-pressure-measurement.md` cites the spec
(name/version/URL) — created as part of this spec (FR-HH-5, NFR-HH-4).

### 6. `ComponentVitalMapper` — `fhir/mappers.py` + `fhir/__init__.py` (FR-HH-3)

Replace the `NotImplementedError` stub body with a real implementation that mirrors
`ScalarVitalMapper` but emits `component[]` instead of a top-level `valueQuantity`:

```python
def to_observation(self, vital, patient_ref, device_ref, issued) -> Observation:
    from fhir.resources.R4B.observation import Observation
    if not isinstance(vital, ComponentVital):
        raise TypeError(...)
    vc = type(vital)
    data = {
        "id": str(uuid.uuid4()),
        "meta": {"profile": [vc.us_core_profile]},
        "status": "final",
        "category": [ ...vital-signs... ],
        "code": {"coding": [{"system": _LOINC_SYSTEM, "code": vc.loinc_code}]},  # panel
        "subject": {"reference": patient_ref},
        "device": {"reference": device_ref},
        "effectiveDateTime": _to_utc_isoformat(vital.effective),
        "issued": _to_utc_isoformat(issued),
        "component": [
            {
                "code": {"coding": [{"system": _LOINC_SYSTEM, "code": spec.loinc_code}]},
                "valueQuantity": {"value": value, "unit": spec.ucum_unit,
                                  "system": _UCUM_SYSTEM, "code": spec.ucum_unit},
            }
            for spec, value in vital.component_values()
        ],
    }
    return Observation.model_validate(data)
```

No panel-level `valueQuantity` (US Core BP profile carries values only in components — FR-HH-3).
Registration in `fhir/__init__.py`: `register_mapper(ComponentVital, ComponentVitalMapper())`
alongside the existing scalar registration. `resolve_mapper` walks the MRO, so `BloodPressure`
resolves to `ComponentVitalMapper` and `HeartRate` still resolves to `ScalarVitalMapper` — no change
to scalar resolution (verified by existing tests).

**Reuse note:** `_to_utc_isoformat`, `_LOINC_SYSTEM`, `_UCUM_SYSTEM`, `_CATEGORY_SYSTEM` already
exist in `mappers.py`; the component mapper reuses them. The `unit` display for BP uses the UCUM code
`mm[Hg]` directly (acceptable; the scalar mapper uses a separate display constant for `/min`, which
is HR-specific — for BP we set both `unit` and `code` to `mm[Hg]`).

### 7. Validation — `validation/builtin/validators.py` (FR-HH-7)

The existing `PlausibleRangeValidator` and `DuplicateValidator` only handle `ScalarVital` (they pass
non-scalars through). Rather than overload them, add a sibling:

```python
class ComponentRangeValidator(Validator):
    """Rejects a ComponentVital if any component value is outside its bounds.

    Bounds come from an optional per-(vital-class, field) override mapping
    (wired from VOF_BP_* config in cli.py); otherwise from the ComponentSpec
    default_range. Non-component vitals pass through.
    """
    name = "component_range"
    def __init__(self, overrides: dict[tuple[type, str], tuple[float, float]] | None = None): ...
    def check(self, vital):
        if not isinstance(vital, ComponentVital): 
            return accepted
        for spec, value in vital.component_values():
            low, high = overrides.get((type(vital), spec.field_name), spec.default_range)
            if not (low <= value <= high): return rejected(...)  # reason has no value
        return accepted
```

Rejection reasons must not include the measurement value (NFR-HH-5); the reason names the component
and bounds only. `SensorContactValidator` already passes non-HR vitals through unchanged (it uses
`getattr(vital, "sensor_contact", None)`), so BP is unaffected by it.

**Duplicate detection — minimal generalization to components.** `DuplicateValidator` currently keys
on `(device_id, effective, value)` and silently accepts every non-`ScalarVital`, which is a latent
gap for *all* component vitals, not just BP. We close it minimally: extend the identity key so a
`ComponentVital` is keyed on `(device_id, effective, component_values-tuple)`, reusing the same
`component_values()` surface the mapper and range validator use. Scalars are unchanged.

Scope is deliberately limited to the identity key — **no** configurable dedup windows, fuzzy
matching, or time-bucketing (YAGNI). The concrete case that earns this is **store-and-forward**
(FR-HH-6), which this spec introduces: a buffered device re-sending its backlog on reconnect can
legitimately deliver the same reading twice, and exact-match component dedup is what guards against
that. This is a change from the earlier "skip dedup for BP" position, justified because the store-
and-forward feature added here creates the real need and the fix is near-free via `component_values()`.

```python
# in DuplicateValidator.check:
if isinstance(vital, ScalarVital):
    key = (vital.device_id, vital.effective, vital.value)
elif isinstance(vital, ComponentVital):
    key = (vital.device_id, vital.effective, vital.component_values())
else:
    return accepted   # unknown shape: don't dedupe
```

### 8. Configuration — `config.py` + `.env.example` (FR-HH-7)

Add four settings (defaults chosen as clinically wide plausibility bounds, not diagnostic ranges):

```python
bp_systolic_min: float = 50.0
bp_systolic_max: float = 250.0
bp_diastolic_min: float = 30.0
bp_diastolic_max: float = 150.0
```

`env_prefix="VOF_"` maps these to `VOF_BP_SYSTOLIC_MIN` etc. `extra="forbid"` still applies. Add all
four to `.env.example` with comments. `cli.py` builds the `ComponentRangeValidator` overrides mapping
`{(BloodPressure, "systolic"): (settings.bp_systolic_min, settings.bp_systolic_max), ...}` and adds
the validator to the chain.

### 9. CLI wiring — `cli.py` (FR-HH-9)

- `_resolve_adapter`: add `"bp"` → `BloodPressureBleAdapter` and `"mock-bp"` → `MockBloodPressureAdapter`,
  alongside `mock`/`miband10`. Fully-qualified class path resolution is unchanged, so third-party BP
  adapters need no repo change.
- `_build_orchestrator`: append `ComponentRangeValidator(overrides)` to the `ValidatorChain`. Order:
  existing scalar validators first, then component validator; each is a no-op for vitals it doesn't
  handle, so order is safe.
- No orchestrator change is needed for mapper dispatch. Confirmed against `pipeline/orchestrator.py`:
  `run()` already calls `resolve_mapper(type(vital))` per reading, so once `ComponentVitalMapper` is
  registered for `ComponentVital`, `BloodPressure` dispatches to it automatically while `HeartRate`
  still resolves to `ScalarVitalMapper`. The `mapper` constructor arg is retained but resolution is
  per-vital via the registry.

### 10. Mock blood-pressure source — `adapters/builtin/mock.py` (FR-HH-9)

The existing `MockAdapter` is HR-specific (hard-codes `HeartRate`). Rather than complicate it, add a
parallel `MockBloodPressureAdapter` in the same module, same structure, emitting `BloodPressure`:

```python
class BloodPressureEmissionMode(enum.Enum):
    VALID = "valid"                 # 118/76
    IMPLAUSIBLE_SYSTOLIC = "..."    # systolic above bound
    IMPLAUSIBLE_DIASTOLIC = "..."   # diastolic above bound
    STORE_AND_FORWARD = "..."       # effective set in the past (issued != effective)

class MockBloodPressureAdapter(DeviceAdapter):
    supported_vitals = (BloodPressure,)
    # connect/disconnect/state mirror MockAdapter; vitals() yields BloodPressure; no bleak
```

`STORE_AND_FORWARD` mode yields a reading whose `effective` is minutes in the past so the
effective≠issued path (FR-HH-6) is testable without hardware. Never imports `bleak`.

---

## Data Models

`BloodPressure` (frozen, kw_only): `effective: datetime` (tz-aware, inherited), `device_id: str`
(inherited), `systolic: float`, `diastolic: float`. Class metadata: panel `loinc_code` `85354-9`,
`us_core_profile` US Core BP, `components` (systolic 8480-6, diastolic 8462-4, both `mm[Hg]`).

`ComponentSpec` (frozen): `field_name`, `loinc_code`, `ucum_unit`, `default_range`.

Produced FHIR `Observation` (US Core Blood Pressure) — shape:

```jsonc
{
  "resourceType": "Observation",
  "id": "<uuid4>",
  "meta": {"profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-blood-pressure"]},
  "status": "final",
  "category": [{"coding": [{"system": ".../observation-category", "code": "vital-signs", ...}]}],
  "code": {"coding": [{"system": "http://loinc.org", "code": "85354-9"}]},
  "subject": {"reference": "Patient/local-patient"},
  "device":  {"reference": "Device/<slug>"},
  "effectiveDateTime": "2026-09-23T12:00:00+00:00",
  "issued":            "2026-09-23T12:03:00+00:00",
  "component": [
    {"code": {"coding": [{"system": "http://loinc.org", "code": "8480-6"}]},
     "valueQuantity": {"value": 118, "unit": "mm[Hg]", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"}},
    {"code": {"coding": [{"system": "http://loinc.org", "code": "8462-4"}]},
     "valueQuantity": {"value": 76,  "unit": "mm[Hg]", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"}}
  ]
}
```

---

## Error Handling

- **Malformed / unusable payload** (short, reserved SFLOAT NaN/NRes): parser returns `None`; adapter
  drops it, logs at `DEBUG` with byte length only (no values). (FR-HH-5, NFR-HH-5)
- **Out-of-range component**: `ComponentRangeValidator` rejects; orchestrator logs at `INFO` with the
  component name and bounds but **not** the value. (FR-HH-7, NFR-HH-5)
- **Observation construction failure**: `Observation.model_validate` raises; orchestrator boundary
  catches, logs at `ERROR` (no values), does not store/serve. (FR-HH-3)
- **`bleak` unavailable**: `BleConnection` raises a clear `RuntimeError` via the existing lazy-import
  guard. Mock BP path needs no Bluetooth stack. (FR-HH-4)
- **Naive `effective` timestamp**: `BloodPressure` construction path requires tz-aware; the parser
  always produces tz-aware (decoded timestamp assumed UTC, or `now(UTC)`). (FR-HH-6)

---

## Testing Strategy

Fast suite, no hardware (NFR-HH-6). New tests mirror `tests/` structure:

- `vitals/`: `BloodPressure.__init_subclass__` metadata enforcement (missing `components`, missing
  field, missing panel code all raise at import); `component_values()` returns declared order;
  frozen/immutability.
- `adapters/`: `bp_parser` pure-function tests — SFLOAT decode (incl. reserved NaN/NRes → unusable),
  flags decode, `required_length`, kPa→mmHg, timestamp decode; `parse()` well-formed mmHg, well-formed
  kPa, timestamp-present (store-and-forward), short/malformed → `None`. Property-based (Hypothesis)
  for SFLOAT round-trips where practical. `MockBloodPressureAdapter` emission modes.
- `adapters/` contract: `BloodPressureBleAdapter` satisfies the `DeviceAdapter` contract suite;
  `BleConnection` behavior (state transitions, drop-None, disconnect unblocks `vitals()`), including
  that a connected adapter emitting no reading for an interval does not surface as disconnection
  (FR-HH-6 liveness).
- `fhir/`: `ComponentVitalMapper` builds a valid US Core BP Observation (validated by
  `fhir.resources`), values in `component[]`, no panel `valueQuantity`; registry resolves
  `BloodPressure → ComponentVitalMapper` and still `HeartRate → ScalarVitalMapper`.
- `validation/`: `ComponentRangeValidator` accepts in-range, rejects each out-of-range component,
  passes non-component vitals through, reason contains no value.
- `config/`: `VOF_BP_*` load, defaults, `extra="forbid"` still rejects unknown vars.
- **Regression guardrail:** full existing suite + `test_dependency_directions.py` stay green after the
  `BleConnection` extraction (NFR-HH-1, NFR-HH-2, NFR-HH-6).
- Hardware tests for a real cuff carry the `hardware` marker, excluded from CI.

---

## Resolved decisions

All prior open questions are resolved:

1. **Duplicate detection** — `DuplicateValidator` is minimally generalized to component vitals
   (identity key extended via `component_values()`; no new dedup features). Justified by the
   store-and-forward feature this spec adds. See the Validation section.
2. **Orchestrator mapper dispatch** — no change needed; `orchestrator.run()` already resolves the
   mapper per-vital via `resolve_mapper`, confirmed against `pipeline/orchestrator.py`. Registering
   `ComponentVitalMapper` for `ComponentVital` is sufficient.
3. **Adapter short names** — `"bp"` (built-in BLE) and `"mock-bp"` (mock).
4. **Device timestamp timezone** — interpreted as host local time and returned tz-aware; documented
   tradeoff in the parser section.
```
