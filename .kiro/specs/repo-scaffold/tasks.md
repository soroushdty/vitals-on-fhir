# Tasks — repo-scaffold

## Task list

- [x] 1. Create `pyproject.toml` and sync dependencies
  - Write `pyproject.toml` with project metadata, runtime deps (`bleak`, `fhir-resources`,
    `fastapi`, `uvicorn[standard]`, `pydantic-settings`), dev deps (`pytest`, `hypothesis`,
    `ruff`, `mypy`, `httpx`), ruff config, mypy strict config, pytest config with `hardware`
    marker, and the `vitals-on-fhir` CLI entry point.
  - Run `uv sync` to generate `uv.lock`.
  - **Verification**: `uv sync` exits 0; `uv.lock` exists.

- [x] 2. Scaffold `vitals/` package
  - Create `src/vitals_on_fhir/__init__.py` (package root stub).
  - Create `src/vitals_on_fhir/vitals/base.py`: `VitalSign`, `ScalarVital`, `ComponentVital`
    ABCs, `DeviceInfo` frozen dataclass — stubs with correct signatures and `ClassVar` fields.
  - Create `src/vitals_on_fhir/vitals/builtin/heart_rate.py`: `HeartRate(ScalarVital)` with
    all `ClassVar` metadata populated.
  - Create `src/vitals_on_fhir/vitals/__init__.py` and `vitals/builtin/__init__.py` with
    correct `__all__`.
  - **Verification**: `from vitals_on_fhir.vitals import HeartRate, VitalSign, DeviceInfo`
    succeeds; `mypy src` passes for this subtree.

- [x] 3. Scaffold `adapters/` package
  - Create `base.py`: `ConnectionState(Enum)`, `DeviceAdapter(ABC)`.
  - Create `ble.py`: `GattCharacteristicParser(ABC)`, `BleHeartRateAdapter(ABC)`. No top-level
    `bleak` import.
  - Create `parser.py`: `HeartRateMeasurementParser` stub.
  - Create `builtin/miband10.py`: `MiBand10Adapter` stub.
  - Create `builtin/mock.py`: `MockAdapter` stub.
  - Create `__init__.py` files with correct `__all__`.
  - **Verification**: `from vitals_on_fhir.adapters import MockAdapter` succeeds; no `bleak`
    top-level import present (`grep -r "^import bleak\|^from bleak" src/vitals_on_fhir/adapters/`
    returns no hits except inside method bodies).

- [x] 4. Scaffold `validation/` package
  - Create `base.py`: `ValidationResult` frozen dataclass, `Validator(ABC)`, `ValidatorChain`.
  - Create `builtin/validators.py`: `PlausibleRangeValidator`, `SensorContactValidator`,
    `DuplicateValidator` stubs.
  - Create `__init__.py` files with correct `__all__`.
  - **Verification**: `from vitals_on_fhir.validation import ValidatorChain` succeeds.

- [x] 5. Scaffold `fhir/` package
  - Create `base.py`: `VitalMapper(ABC)`, mapper registry helpers (`register_mapper`,
    `resolve_mapper`).
  - Create `mappers.py`: `ScalarVitalMapper`, `ComponentVitalMapper` stubs.
  - Create `builders.py`: four builder function stubs with correct signatures.
  - Create `__init__.py` files with correct `__all__`.
  - **Verification**: `from vitals_on_fhir.fhir import ScalarVitalMapper, build_device`
    succeeds.

- [x] 6. Scaffold `pipeline/` package
  - Create `base.py`: `ObservationSink(ABC)`.
  - Create `orchestrator.py`: `Orchestrator` class stub.
  - Create `__init__.py` files with correct `__all__`.
  - **Verification**: `from vitals_on_fhir.pipeline import ObservationSink, Orchestrator`
    succeeds.

- [x] 7. Scaffold `store/` package
  - Create `base.py`: `ObservationStore(ABC)`.
  - Create `memory.py`: `InMemoryObservationStore(ObservationStore, ObservationSink)` stub.
  - Create `__init__.py` files with correct `__all__`.
  - **Verification**: `from vitals_on_fhir.store import InMemoryObservationStore` succeeds.

- [x] 8. Scaffold `api/` package
  - Create `auth.py`: `Authenticator(ABC)`, `StaticTokenAuthenticator` stub.
  - Create `routes.py`: stub async route function stubs.
  - Create `app.py`: `create_app()` factory stub.
  - Create `__init__.py` files with correct `__all__`.
  - **Verification**: `from vitals_on_fhir.api import create_app` succeeds.

- [x] 9. Scaffold `dashboard/` package and static assets
  - Create `broadcaster.py`: `DashboardBroadcaster(ObservationSink)` stub.
  - Create `static/index.html`, `static/style.css`, `static/app.js` placeholder files.
  - Create `__init__.py` with correct `__all__`.
  - **Verification**: `from vitals_on_fhir.dashboard import DashboardBroadcaster` succeeds.

- [x] 10. Create `config.py` and `cli.py`
  - `config.py`: `Settings(BaseSettings)` with all `VOF_*` fields, correct defaults,
    `env_prefix="VOF_"`, `extra="forbid"`.
  - `cli.py`: `main()` stub (composition root).
  - **Verification**: `from vitals_on_fhir.config import Settings` succeeds; `Settings()`
    can be instantiated when `VOF_API_TOKEN` is supplied.

- [x] 11. Create test skeleton and `test_dependency_directions.py`
  - Create all `tests/` subdirectories and `__init__.py` files.
  - Create `tests/conftest.py` with a placeholder comment.
  - Create placeholder test files (one placeholder comment each) for every module listed in
    FR-S4.
  - Write `tests/test_dependency_directions.py`: complete AST-based enforcement test ported
    from EviTrace (AGPL-compatible; EviTrace entry already in NOTICE).
  - **Verification**: `uv run pytest tests/test_dependency_directions.py` passes.

- [x] 12. Update top-level files
  - Update `README.md`: project title, mission paragraph, not-a-medical-device disclaimer,
    quick-start instructions, HIPAA disclaimer, BLE security note, HL7/FHIR trademark notice.
  - Create `.env.example` with all `VOF_*` variables and placeholder values.
  - Create `docs/README.md` stub.
  - Prepend a `[2026-09] — Repository scaffold (spec/repo-scaffold)` entry to `CHANGELOG.md`.

- [x] 13. Create CI workflow
  - Create `.github/workflows/ci.yml` with the four-step pipeline: checkout → setup-uv →
    `uv sync` → `ruff check` → `mypy src` → `pytest`.
  - **Verification**: YAML is valid (`python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`).

- [x] 14. Final verification
  - Run `uv run ruff check .` — must report zero errors.
  - Run `uv run mypy src` — must report zero errors.
  - Run `uv run pytest` — all tests pass (no hardware tests run).
  - Confirm `uv run vitals-on-fhir --help` (or equivalent) exits without import errors.
