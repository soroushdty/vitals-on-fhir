---
inclusion: always
---

# Structure — vitals-on-fhir

## Directory layout

```
vitals-on-fhir/
├── src/
│   └── vitals_on_fhir/
│       ├── vitals/              # VitalSign ABCs + DeviceInfo; depends on nothing else
│       │   ├── __init__.py
│       │   ├── base.py          # VitalSign, ScalarVital, ComponentVital ABCs; DeviceInfo
│       │   └── builtin/
│       │       ├── __init__.py
│       │       └── heart_rate.py  # HeartRate
│       ├── adapters/            # DeviceAdapter, BleHeartRateAdapter, parsers
│       │   ├── __init__.py
│       │   ├── base.py          # DeviceAdapter ABC, ConnectionState enum
│       │   ├── ble.py           # BleHeartRateAdapter ABC, GattCharacteristicParser ABC
│       │   ├── parser.py        # HeartRateMeasurementParser + pure parsing functions
│       │   └── builtin/
│       │       ├── __init__.py
│       │       ├── miband10.py  # MiBand10Adapter
│       │       └── mock.py      # MockAdapter
│       ├── validation/          # Validator ABC, ValidationResult, ValidatorChain
│       │   ├── __init__.py
│       │   ├── base.py
│       │   └── builtin/
│       │       ├── __init__.py
│       │       └── validators.py  # PlausibleRangeValidator, SensorContactValidator, DuplicateValidator
│       ├── fhir/                # VitalMapper ABC + mappers, resource builders
│       │   ├── __init__.py
│       │   ├── base.py          # VitalMapper ABC, mapper registry
│       │   ├── mappers.py       # ScalarVitalMapper, ComponentVitalMapper
│       │   └── builders.py      # Device, Patient, CapabilityStatement, OperationOutcome builders
│       ├── pipeline/            # ObservationSink ABC, orchestrator
│       │   ├── __init__.py
│       │   ├── base.py          # ObservationSink ABC
│       │   └── orchestrator.py  # Wires adapter → validators → mapper → sinks
│       ├── store/               # ObservationStore ABC + InMemoryObservationStore
│       │   ├── __init__.py
│       │   ├── base.py
│       │   └── memory.py        # InMemoryObservationStore (also an ObservationSink)
│       ├── api/                 # FastAPI routes, Authenticator ABC
│       │   ├── __init__.py
│       │   ├── auth.py          # Authenticator ABC, StaticTokenAuthenticator
│       │   ├── routes.py        # Route functions (plain async def, DI for store + auth)
│       │   └── app.py           # FastAPI app factory
│       ├── dashboard/           # Static assets + DashboardBroadcaster
│       │   ├── __init__.py
│       │   ├── broadcaster.py   # DashboardBroadcaster (ObservationSink + WS push)
│       │   └── static/          # HTML, CSS, JS — no build step
│       ├── config.py            # pydantic-settings Settings class
│       └── cli.py               # Composition root — the only module that imports concrete classes
├── tests/                       # Mirrors src/vitals_on_fhir/; plus cross-cutting tests
│   ├── vitals/
│   ├── adapters/
│   ├── validation/
│   ├── fhir/
│   ├── pipeline/
│   ├── store/
│   ├── api/
│   ├── dashboard/
│   ├── test_dependency_directions.py   # AST-based; enforces the table below
│   └── conftest.py
├── docs/                        # SRS, architecture decisions, protocol sources
├── CHANGELOG.md
├── NOTICE
├── LICENSE
├── .env.example
├── pyproject.toml
└── .kiro/
    └── steering/
```

## Module responsibilities

| Module | Owns | Does not own |
|--------|------|--------------|
| `vitals/` | Domain model: what a vital sign is | FHIR, BLE, validation logic |
| `adapters/` | Device connectivity and payload parsing | FHIR, validation, storage |
| `validation/` | Accept/reject decisions on VitalSign objects | Parsing, FHIR, storage |
| `fhir/` | VitalSign → FHIR Observation conversion and resource building | Connectivity, validation, storage |
| `pipeline/` | Orchestration flow: adapter → validators → mapper → sinks | Concrete sinks, storage details |
| `store/` | Storing and querying Observations | HTTP serving, auth |
| `api/` | HTTP routes and auth | Business logic, storage implementation |
| `dashboard/` | WebSocket push and static UI | HTTP routes, auth logic |
| `config.py` | Typed settings loaded from environment | Everything else |
| `cli.py` | Composition root: wires everything together | Business logic |

## Dependency direction rules

Enforced by `tests/test_dependency_directions.py`. A failing test means a forbidden cross-package import was introduced.

| Package | Must NOT import |
|---------|----------------|
| `vitals` | any other `vitals_on_fhir` package |
| `adapters` | `validation`, `fhir`, `pipeline`, `store`, `api`, `dashboard`, `cli` |
| `validation` | `adapters`, `fhir`, `pipeline`, `store`, `api`, `dashboard`, `cli` |
| `fhir` | `adapters`, `validation`, `pipeline`, `store`, `api`, `dashboard`, `cli` |
| `pipeline` | `store`, `api`, `dashboard`, `cli` |
| `store` | `adapters`, `validation`, `api`, `dashboard`, `cli` |
| `api` | `adapters`, `validation`, `pipeline`, `dashboard`, `cli` |
| `dashboard` | `adapters`, `validation`, `api`, `cli` |

`cli.py` is the only module that may import from all packages.

Run `uv run pytest tests/test_dependency_directions.py` after any cross-package import change.

## `__init__.py` and public API conventions

- Every package's `__init__.py` defines `__all__`, grouped into two sections: `# ABCs` and `# Concrete defaults`.
- Consumers import from the package, never from internal modules: `from vitals_on_fhir.vitals import HeartRate`, not `from vitals_on_fhir.vitals.builtin.heart_rate import HeartRate`.
- Names in `__all__` are the public API. Changing them is a breaking change requiring a `CHANGELOG.md` entry.
- Internal modules (not in `__all__`) may be renamed freely. Do not import them directly from outside their package.
- One name per concept: no alias properties or duplicate re-exports.

## Naming conventions

| Kind | Convention | Example |
|------|-----------|---------|
| Concrete device adapter | `<Device>Adapter` | `MiBand10Adapter` |
| Vital-sign class | Named for the measured quantity | `HeartRate`, `OxygenSaturation` |
| ABC | Named by capability | `DeviceAdapter`, `ObservationSink`, `Validator` |
| Parser class | `<Profile>Parser` | `HeartRateMeasurementParser` |
| Store class | `<Implementation>ObservationStore` | `InMemoryObservationStore` |
| Mapper class | `<Kind>VitalMapper` | `ScalarVitalMapper` |
| Config variable | `VOF_<SCREAMING_SNAKE>` | `VOF_API_TOKEN` |
| Test file | `test_<module_name>.py` | `test_heart_rate.py` |

## Special files

- **`CHANGELOG.md`**: permanent record; see `changelog-rules.md` for format.
- **`NOTICE`**: records EviTrace-ported code and any other third-party inclusions. Required entry format: source project, license, URL, and which files in this repo contain ported material.
- **`docs/`**: SRS, architecture decision records (ADRs), and protocol source citations. Protocol knowledge must be cited here, not embedded only in code comments.
- **`.env.example`**: lists every `VOF_*` variable with a description; never commit a populated `.env`.
