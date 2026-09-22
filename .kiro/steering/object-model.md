---
inclusion: always
---

# Object model — vitals-on-fhir

Every extension point is an ABC. Concrete defaults live in `builtin/` subpackages next to their ABCs. Consumers subclass the ABCs; they never modify the repository.

---

## 1. Vital signs (`vitals/`)

The domain model. Depends on nothing else in this project.

### Class hierarchy

```
VitalSign (ABC, frozen dataclass)
├── ScalarVital (ABC)
│   └── HeartRate (concrete)              — LOINC 8867-4
└── ComponentVital (ABC)                  — roadmap: BloodPressure
```

### `VitalSign` (ABC)

```python
@dataclass(frozen=True, kw_only=True)
class VitalSign(ABC):
    effective: datetime   # timezone-aware; when the measurement was taken
    device_id: str

    # Required class metadata (enforced in __init_subclass__ for concrete subclasses)
    loinc_code: ClassVar[str]
    us_core_profile: ClassVar[str]
```

Rules:
- `effective` must be timezone-aware. Store-and-forward: `effective` (measurement time → `effectiveDateTime`) may differ from `issued` (processing time); always set both.
- `device_id` links the reading to a Device resource.
- Missing `loinc_code` or `us_core_profile` on a concrete subclass raises at import time (`__init_subclass__`).
- No FHIR code in this package — no `to_fhir()` methods.

### `ScalarVital` (ABC, subclasses `VitalSign`)

Adds:
- Instance field: `value` (numeric measurement)
- Required class metadata: `ucum_unit: ClassVar[str]`, `plausible_range: ClassVar[tuple[float, float]]`

### `ComponentVital` (ABC, subclasses `VitalSign`)

For multi-component readings (e.g. blood pressure: systolic + diastolic). Defines the component structure. No concrete subclass in the MVP; the hierarchy must accommodate it without changes.

### `HeartRate` (concrete, `vitals/builtin/`)

```python
@dataclass(frozen=True, kw_only=True)
class HeartRate(ScalarVital):
    loinc_code: ClassVar[str] = "8867-4"
    ucum_unit: ClassVar[str] = "/min"
    us_core_profile: ClassVar[str] = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-heart-rate"
    plausible_range: ClassVar[tuple[float, float]] = (20.0, 250.0)

    sensor_contact: bool | None = None  # from the BLE flags byte
```

### `DeviceInfo` (frozen dataclass)

```python
@dataclass(frozen=True)
class DeviceInfo:
    manufacturer: str
    model: str
    identifiers: dict[str, str]  # e.g. {"bluetooth_address": "AA:BB:CC:DD:EE:FF"}
```

Used by adapters to populate the FHIR Device resource. Expandable for roadmap Device Information Service support.

---

## 2. Adapters (`adapters/`)

### `ConnectionState` (Enum)

Plain `enum.Enum`. Values: `DISCONNECTED`, `CONNECTING`, `CONNECTED`, `RECONNECTING`. No methods.

### `DeviceAdapter` (ABC)

```python
class DeviceAdapter(ABC):
    supported_vitals: ClassVar[tuple[type[VitalSign], ...]]

    @property
    @abstractmethod
    def device_info(self) -> DeviceInfo: ...

    @property
    @abstractmethod
    def state(self) -> ConnectionState: ...

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def vitals(self) -> AsyncIterator[VitalSign]: ...
```

Contract: `vitals()` is an async generator that yields `VitalSign` objects indefinitely until disconnected. Adapters yield domain objects only — no FHIR, no validation logic.

### `GattCharacteristicParser` (ABC)

```python
class GattCharacteristicParser(ABC):
    @abstractmethod
    def parse(self, data: bytes) -> VitalSign | None: ...
```

Returns `None` for malformed payloads (drops them silently at the adapter boundary). `HeartRateMeasurementParser` is the shipped concrete parser for `0x2A37`; byte-level logic lives in pure functions that the class delegates to.

### `BleHeartRateAdapter` (ABC, subclasses `DeviceAdapter`)

Implements: BLE scanning, subscribing to `0x2A37`, parsing via `HeartRateMeasurementParser`, reconnection loop. Leaves abstract: `matches(advertisement)` and `device_info`. Imports `bleak` lazily inside its methods.

### `MiBand10Adapter` (concrete, `adapters/builtin/`)

Reference implementation. Implements `matches()` and `device_info` for the Xiaomi Smart Band 10.

### `MockAdapter` (concrete, `adapters/builtin/`)

Simulated-data implementation. Never imports `bleak`. Configurable to emit valid readings, implausible values, and readings with missing sensor contact, to exercise the full validator chain in tests.

---

## 3. Validation (`validation/`)

Strategy pattern.

### `ValidationResult` (frozen dataclass)

```python
@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    validator_name: str
    reason: str | None = None
```

### `Validator` (ABC)

```python
class Validator(ABC):
    name: ClassVar[str]

    @abstractmethod
    def check(self, vital: VitalSign) -> ValidationResult: ...
```

### `ValidatorChain`

Runs validators in registration order. Returns the first rejection. If all pass, returns an accepted result. Not an ABC — instantiate directly.

### Concrete validators (shipped in `validation/builtin/`)

| Class | Rejects when |
|-------|-------------|
| `PlausibleRangeValidator` | `value` outside `vital_class.plausible_range`; range overridable from config (`VOF_HR_MIN`, `VOF_HR_MAX`) |
| `SensorContactValidator` | `sensor_contact is False` (passes when `None`, i.e. sensor contact not reported) |
| `DuplicateValidator` | same `(device_id, effective, value)` seen already in this session |

---

## 4. FHIR mapping (`fhir/`)

### `VitalMapper` (ABC)

```python
class VitalMapper(ABC):
    @abstractmethod
    def to_observation(
        self,
        vital: VitalSign,
        patient_ref: str,
        device_ref: str,
        issued: datetime,
    ) -> Observation: ...
```

### `ScalarVitalMapper` (concrete)

Builds an Observation entirely from `ScalarVital` class metadata (`loinc_code`, `ucum_unit`, `us_core_profile`). A new scalar vital sign needs no mapper code.

### `ComponentVitalMapper` (concrete, roadmap-ready stub)

Handles `ComponentVital` subclasses. No concrete vital uses it in the MVP.

### Mapper registry

Resolves the mapper for a vital-sign class by walking its MRO. A subclass inherits its parent's mapper unless one is registered explicitly. Registration is done in `fhir/__init__.py`.

### Resource builders (in `fhir/builders.py`)

Plain functions (not classes) that return `fhir.resources` model instances:
- `build_device(device_info) -> Device`
- `build_patient(patient_id) -> Patient`
- `build_capability_statement() -> CapabilityStatement`
- `build_operation_outcome(severity, code, diagnostics) -> OperationOutcome`

---

## 5. Pipeline (`pipeline/`)

### `ObservationSink` (ABC)

```python
class ObservationSink(ABC):
    @abstractmethod
    async def publish(self, observation: Observation) -> None: ...
```

Observer pattern. The orchestrator fans each Observation out to every registered sink.

### Orchestrator

Wires: `DeviceAdapter` → `ValidatorChain` → `VitalMapper` → `list[ObservationSink]`. Depends on ABCs only. Concrete classes are chosen and injected in `cli.py`.

---

## 6. Store (`store/`)

### `ObservationStore` (ABC)

```python
class ObservationStore(ABC):
    @abstractmethod
    async def add(self, observation: Observation) -> None: ...

    @abstractmethod
    async def get(self, observation_id: str) -> Observation | None: ...

    @abstractmethod
    async def search(
        self,
        *,
        code: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        sort_desc: bool = True,
        count: int | None = None,
    ) -> list[Observation]: ...
```

### `InMemoryObservationStore` (concrete, also an `ObservationSink`)

- Bounded by `VOF_STORE_MAX`; evicts oldest when full.
- Protected with `asyncio.Lock`; reads return snapshots.
- Implements both `ObservationStore` and `ObservationSink`.

---

## 7. API (`api/`)

### `Authenticator` (ABC)

```python
class Authenticator(ABC):
    @abstractmethod
    def authenticate(self, credentials: str) -> bool: ...
```

### `StaticTokenAuthenticator` (concrete)

Compares `credentials` to `VOF_API_TOKEN` using a constant-time comparison. SMART on FHIR is roadmap.

Route functions are plain `async def`. Store and authenticator are injected via `FastAPI.Depends()`.

---

## 8. Dashboard (`dashboard/`)

### `DashboardBroadcaster` (concrete `ObservationSink`)

- Maintains a set of active, authenticated WebSocket connections.
- On `publish()`, serializes the Observation to FHIR JSON and sends to all connected clients.
- Also relays `ConnectionState` changes from the adapter so the dashboard shows disconnection in real time.

---

## OOP conventions

- Every ABC inherits from `abc.ABC`. This includes ABCs that are also dataclasses.
- `@abstractmethod` without `ABC` in the bases is not enforced by Python — always include `ABC`.
- Keep each ABC to one responsibility with a small number of abstract members.
- A subclass must never implement an inherited abstract method by raising `NotImplementedError`. If it would need to, split the interface.
- Prefer composition over inheritance outside the hierarchies above (adapters *have* parsers; the pipeline *has* validators and sinks).
- Keep inheritance hierarchies to at most three levels.
- Domain objects and results are immutable (frozen dataclasses).
- One name per concept: no alias properties or duplicate re-exports.
- ABCs are public API. Changes to them are breaking changes requiring a `CHANGELOG.md` entry.

## Where NOT to use OOP

- **FHIR resources**: use `fhir.resources` model classes directly; do not subclass.
- **API routes**: plain `async def` functions with dependency injection; no route classes.
- **Byte-level parsing internals**: pure functions called by the parser class.
- **Connection state**: a plain `Enum`, not a class hierarchy.

---

## Extension recipes

### Recipe 1 — Adding a scalar vital sign

1. Create `vitals/builtin/<name>.py`. Define a frozen dataclass subclassing `ScalarVital`. Set `loinc_code`, `ucum_unit`, `us_core_profile`, `plausible_range` as class variables. Add domain-specific instance fields if needed (e.g. `sensor_contact` on `HeartRate`).
2. Export from `vitals/__init__.py` under `# Concrete defaults`.
3. Add a `PlausibleRangeValidator` config pair if the range should be configurable (add `VOF_<VITAL>_MIN` / `MAX` to `config.py` and `Settings`).
4. No mapper code needed: `ScalarVitalMapper` builds the Observation from class metadata.
5. Add an `__init_subclass__` unit test asserting the metadata is present (see `testing.md`).
6. Add a `CHANGELOG.md` entry.

### Recipe 2 — Adding a BLE Heart Rate Service device

1. Create `adapters/builtin/<device>.py`. Define a class subclassing `BleHeartRateAdapter`.
2. Implement `matches(advertisement) -> bool` using the device's advertised name or service UUID.
3. Implement the `device_info` property returning a `DeviceInfo` with manufacturer and model.
4. Register the short name in the adapter loader in `cli.py` (e.g. `"mystrap"` → `MyStrapAdapter`), or use the fully qualified class path.
5. Do not add any BLE scanning or parsing logic; `BleHeartRateAdapter` handles it.
6. Write a contract test using the reusable `DeviceAdapter` suite (see `testing.md`).
7. Add a `CHANGELOG.md` entry.

### Recipe 3 — Adding a non-BLE adapter

1. Create a module (inside or outside the repository). Define a class subclassing `DeviceAdapter` directly.
2. Implement all abstract members: `device_info`, `state`, `connect()`, `disconnect()`, `vitals()`.
3. `vitals()` must yield `VitalSign` objects only — no FHIR, no validation.
4. Import heavy dependencies lazily inside methods. Never import them at module level.
5. Register by passing the fully qualified class path to `--adapter`.
6. Write a contract test. Third-party adapters can import and run the reusable suite from `tests/`.
7. If adding to the repository: add a `CHANGELOG.md` entry.

### Recipe 4 — Adding an output sink

1. Create a class subclassing `ObservationSink`.
2. Implement `async publish(self, observation: Observation) -> None`.
3. In `cli.py`, instantiate the sink and register it with the orchestrator's sink list.
4. If the sink also needs to act as a store, consider also subclassing `ObservationStore` (like `InMemoryObservationStore` does).
5. Sinks must not raise on publish errors; log and continue so other sinks are unaffected.
6. Add a `CHANGELOG.md` entry if the sink is part of the repository's public API.
