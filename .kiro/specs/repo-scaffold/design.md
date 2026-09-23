# Design — repo-scaffold

## Overview

This spec produces a structurally complete but behaviourally empty repository. Every module
exists, every public name is importable, the dependency-direction invariants hold, and all
tooling (ruff, mypy, pytest) is wired and passing. Feature specs fill in the actual logic.

---

## 1. Project configuration (`pyproject.toml`)

Single source of truth for the toolchain.

```toml
[project]
name = "vitals-on-fhir"
version = "0.1.0"
requires-python = ">=3.12"

[project.scripts]
vitals-on-fhir = "vitals_on_fhir.cli:main"

[tool.ruff]
line-length = 100
target-version = "py312"
src = ["src"]

[tool.mypy]
strict = true
mypy_path = "src"

[tool.pytest.ini_options]
markers = ["hardware: requires a physical BLE device (deselect with '-m not hardware')"]
addopts = "-m 'not hardware'"
testpaths = ["tests"]
```

Dependencies (runtime): `bleak`, `fhir-resources`, `fastapi`, `uvicorn[standard]`,
`pydantic-settings`.
Dependencies (dev): `pytest`, `hypothesis`, `ruff`, `mypy`, `httpx`.

All pinned to exact versions via `uv add` and committed `uv.lock`.

---

## 2. Package stubs

Each stub module follows this template:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later
"""<One-line description of the module's responsibility.>"""
```

Classes and functions that must exist for `__all__` to import correctly are declared with
`pass` / `...` bodies and the correct signatures (including type hints). No imports of
concrete implementations across package boundaries — the dependency-direction rules apply
even to stubs.

### 2.1 `vitals/`

`base.py` declares:
- `VitalSign` — frozen `@dataclass(frozen=True, kw_only=True)` ABC with `effective: datetime`,
  `device_id: str`, `loinc_code: ClassVar[str]`, `us_core_profile: ClassVar[str]`,
  and `__init_subclass__` guard.
- `ScalarVital` — subclasses `VitalSign`; adds `value: float`, `ucum_unit: ClassVar[str]`,
  `plausible_range: ClassVar[tuple[float, float]]`.
- `ComponentVital` — subclasses `VitalSign`; roadmap stub, no additional members in MVP.
- `DeviceInfo` — plain frozen dataclass (no ABC).

`builtin/heart_rate.py` declares `HeartRate(ScalarVital)` with all `ClassVar` metadata set.

`__init__.py` exports:
```python
__all__ = [
    # ABCs
    "VitalSign",
    "ScalarVital",
    "ComponentVital",
    # Concrete defaults
    "HeartRate",
    "DeviceInfo",
]
```

### 2.2 `adapters/`

`base.py` declares `ConnectionState(Enum)` and `DeviceAdapter(ABC)` with all abstract members
stubbed.

`ble.py` declares `GattCharacteristicParser(ABC)` and `BleHeartRateAdapter(ABC, DeviceAdapter)`.
`bleak` is NOT imported at module level — it will be imported lazily inside method bodies in
the feature spec.

`parser.py` declares `HeartRateMeasurementParser(GattCharacteristicParser)` stub.

`builtin/miband10.py` declares `MiBand10Adapter(BleHeartRateAdapter)` stub.
`builtin/mock.py` declares `MockAdapter(DeviceAdapter)` stub.

`__init__.py` exports:
```python
__all__ = [
    # ABCs
    "ConnectionState",
    "DeviceAdapter",
    "GattCharacteristicParser",
    "BleHeartRateAdapter",
    # Concrete defaults
    "HeartRateMeasurementParser",
    "MiBand10Adapter",
    "MockAdapter",
]
```

### 2.3 `validation/`

`base.py` declares `ValidationResult` (frozen dataclass), `Validator(ABC)`, `ValidatorChain`.

`builtin/validators.py` declares `PlausibleRangeValidator`, `SensorContactValidator`,
`DuplicateValidator` — all stubs.

`__init__.py` exports:
```python
__all__ = [
    # ABCs
    "Validator",
    # Concrete defaults
    "ValidationResult",
    "ValidatorChain",
    "PlausibleRangeValidator",
    "SensorContactValidator",
    "DuplicateValidator",
]
```

### 2.4 `fhir/`

`base.py` declares `VitalMapper(ABC)` and the mapper registry (a plain dict, or a simple
`register`/`resolve` function pair). No `fhir.resources` imports are needed in the stub beyond
the return type annotation (use `TYPE_CHECKING` guard if necessary to keep mypy happy).

`mappers.py` declares `ScalarVitalMapper(VitalMapper)` and `ComponentVitalMapper(VitalMapper)`
stubs.

`builders.py` declares the four builder function stubs (`build_device`, `build_patient`,
`build_capability_statement`, `build_operation_outcome`) with correct signatures.

`__init__.py` exports:
```python
__all__ = [
    # ABCs
    "VitalMapper",
    # Concrete defaults
    "ScalarVitalMapper",
    "ComponentVitalMapper",
    "build_device",
    "build_patient",
    "build_capability_statement",
    "build_operation_outcome",
]
```

### 2.5 `pipeline/`

`base.py` declares `ObservationSink(ABC)` with `async publish` stubbed.

`orchestrator.py` declares the `Orchestrator` class stub (wires adapter → validators → mapper →
sinks; all injected, no concrete references).

`__init__.py` exports:
```python
__all__ = [
    # ABCs
    "ObservationSink",
    # Concrete defaults
    "Orchestrator",
]
```

### 2.6 `store/`

`base.py` declares `ObservationStore(ABC)` with `add`, `get`, `search` stubbed.

`memory.py` declares `InMemoryObservationStore(ObservationStore, ObservationSink)` stub.

`__init__.py` exports:
```python
__all__ = [
    # ABCs
    "ObservationStore",
    # Concrete defaults
    "InMemoryObservationStore",
]
```

### 2.7 `api/`

`auth.py` declares `Authenticator(ABC)` and `StaticTokenAuthenticator` stub.

`routes.py` declares stub async route functions (no business logic).

`app.py` declares `create_app` factory stub returning a `FastAPI` instance.

`__init__.py` exports:
```python
__all__ = [
    # ABCs
    "Authenticator",
    # Concrete defaults
    "StaticTokenAuthenticator",
    "create_app",
]
```

### 2.8 `dashboard/`

`broadcaster.py` declares `DashboardBroadcaster(ObservationSink)` stub.

`static/` contains minimal placeholder files:
- `index.html` — bare HTML5 skeleton with a `<title>vitals-on-fhir</title>`
- `style.css` — empty / comment-only
- `app.js` — comment-only

`__init__.py` exports:
```python
__all__ = [
    # Concrete defaults
    "DashboardBroadcaster",
]
```

### 2.9 `config.py`

Declares a `Settings(BaseSettings)` class with all `VOF_*` variables as typed fields, default
values as per the tech steering doc, `model_config = SettingsConfigDict(env_prefix="VOF_",
extra="forbid")`.

### 2.10 `cli.py`

Declares a `main()` function stub (the composition root). The entry point must be importable
without error.

---

## 3. `test_dependency_directions.py`

A complete, runnable test ported from EviTrace. It:

1. Uses Python's `ast` module to parse every `.py` file under `src/vitals_on_fhir/`.
2. For each file, determines which package it belongs to.
3. For each `import` or `from ... import` statement, checks whether the imported package is in
   the forbidden list for the file's package (per the table in the structure steering doc).
4. Fails with a descriptive message naming the offending file and the forbidden import.

No `bleak`, `fhir.resources`, or any third-party import is needed in this test file.

---

## 4. CI workflow (`.github/workflows/ci.yml`)

```yaml
name: CI
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run mypy src
      - run: uv run pytest
```

---

## 5. Dependency-direction compliance

The stubs must satisfy the forbidden-import table. Key rules that affect stub content:

- `vitals/` imports only stdlib (`abc`, `dataclasses`, `datetime`, `typing`).
- `adapters/` imports from `vitals/` and stdlib only. No `bleak` at module level.
- `validation/` imports from `vitals/` and stdlib only.
- `fhir/` imports from `vitals/` and stdlib only (use `TYPE_CHECKING` for `fhir.resources`
  return types if needed to avoid a hard import).
- `pipeline/` imports from `vitals/`, `adapters/`, `validation/`, `fhir/`, and stdlib only.
- `store/` imports from `pipeline/` (for `ObservationSink`), `vitals/`, and stdlib only.
  Actually: `store/` may not import `adapters`, `validation`, `api`, `dashboard`, or `cli`.
  It imports `fhir.resources.Observation` for type hints and `pipeline.base.ObservationSink`.
- `api/` imports from `store/`, `fhir/`, `vitals/`, and stdlib only.
- `dashboard/` imports from `pipeline/`, `fhir/`, `vitals/`, and stdlib only.
- `cli.py` may import from everywhere.

---

## 6. File-by-file creation order

Tasks in the implementation spec follow this order to keep each step independently buildable:

1. `pyproject.toml` + `uv sync`
2. `src/vitals_on_fhir/` package init + `vitals/` subtree
3. `adapters/` subtree
4. `validation/` subtree
5. `fhir/` subtree
6. `pipeline/` subtree
7. `store/` subtree
8. `api/` subtree
9. `dashboard/` subtree (including static files)
10. `config.py` + `cli.py`
11. `tests/` skeleton + `test_dependency_directions.py`
12. Top-level files (`.env.example`, `README.md` update, `CHANGELOG.md` entry, `docs/`)
13. CI workflow
14. Final verification: `ruff check`, `mypy src`, `pytest`
