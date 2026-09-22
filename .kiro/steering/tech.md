---
inclusion: always
---

# Tech — vitals-on-fhir

## Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Language | Python 3.12+ | Async-first, strong typing, rich BLE and FHIR ecosystem |
| Package manager | `uv` | Fast, reproducible, lock-file based |
| Project layout | `src/` layout | Prevents accidental imports of the source tree without install |
| Package name | `vitals_on_fhir` | |
| BLE | `bleak` | Cross-platform async BLE; imported **lazily** inside BLE adapter modules only |
| FHIR models | `fhir.resources` | R4B-compatible, targeting R4 4.0.1 semantics; use its models directly, never subclass or wrap them |
| Web framework | FastAPI | Async, dependency injection, automatic OpenAPI |
| Config | `pydantic-settings` | Type-safe env/`.env` loading with the `VOF_` prefix |
| Linter/formatter | `ruff` | Lint and format in one tool |
| Type checker | `mypy` (strict on `src/`) | Enforced on CI |
| Test framework | `pytest` + `Hypothesis` | Unit, integration, property-based |
| CI | GitHub Actions | Runs on every push and PR |

## Key library constraints

- **`bleak`**: import it only inside BLE adapter modules (i.e. `adapters/builtin/ble_heart_rate.py` and subclasses). Never at module level in `adapters/base.py`, `validation/`, `fhir/`, `pipeline/`, or tests that don't carry the `hardware` marker. This ensures mock mode, tests, and CI work without a Bluetooth stack.
- **`fhir.resources`**: use the library's own model classes for all FHIR resource construction. Do not subclass, wrap, or monkey-patch them. Do not serialize resources manually; use the library's `.model_dump_json()` / `.model_validate()`.
- **FastAPI**: routes are plain `async def` functions. Use FastAPI's `Depends()` for the store and authenticator — never reach for module-level singletons inside route handlers.

## Commands

```bash
# Sync dependencies
uv sync

# Run (mock adapter, no hardware needed)
uv run vitals-on-fhir --adapter mock

# Run (Xiaomi Smart Band 10)
uv run vitals-on-fhir --adapter miband10

# Run (third-party adapter by class path)
uv run vitals-on-fhir --adapter mypackage.adapters.MyStrapAdapter

# Fast test suite (no hardware, default)
uv run pytest

# Tests requiring a real device
uv run pytest -m hardware

# Lint
uv run ruff check .

# Format
uv run ruff format .

# Type check
uv run mypy src
```

## Configuration

Config is loaded once in `cli.py` (the composition root) via `pydantic-settings` and passed explicitly to every component that needs it. No module-level global config object. No mutation of config after startup.

| Variable | Default | Description |
|----------|---------|-------------|
| `VOF_API_TOKEN` | *(required)* | Bearer token for all API requests and dashboard WebSocket |
| `VOF_HOST` | `127.0.0.1` | Bind address |
| `VOF_PORT` | `8000` | HTTP port |
| `VOF_ADAPTER` | `mock` | `mock`, `miband10`, or `package.module.ClassName` |
| `VOF_DEVICE_NAME` | *(none)* | Optional BLE name filter |
| `VOF_HR_MIN` | `20` | Heart-rate plausibility lower bound (bpm) |
| `VOF_HR_MAX` | `250` | Heart-rate plausibility upper bound (bpm) |
| `VOF_PATIENT_ID` | `local-patient` | ID of the local Patient resource |
| `VOF_STORE_MAX` | `10000` | Maximum Observations kept in memory |

Rules:
- Unknown `VOF_*` variables are rejected at startup (pydantic-settings `extra = "forbid"`).
- Provide a `.env.example` listing every variable with a comment; never commit a populated `.env`.
- `VOF_API_TOKEN` must never appear in logs at any level.

## Async conventions

- The entire acquisition-to-sink path is `async` (asyncio).
- Shared mutable state (the observation store) is protected with asyncio primitives (`asyncio.Lock` or similar).
- Store reads return snapshots (copies), never live references.
- Do not use `asyncio.run()` inside library code; only in `cli.py`.
- Do not mix sync and async I/O on the same event loop. BLE callbacks from `bleak` must be converted to coroutines via `loop.call_soon_threadsafe` or equivalent if they arrive on a different thread.

## Coding conventions

- **Type hints everywhere** — all function signatures, including internal helpers. `mypy --strict` must pass on `src/`.
- **Docstrings on public APIs** — every public class, method, and function exported from a package's `__init__.py` needs a docstring. Internal helpers need docstrings only when the intent isn't obvious from the name.
- **SPDX header on every source file**: `# SPDX-License-Identifier: AGPL-3.0-or-later`
- **Lazy optional imports**: `bleak` and any other hardware-only dependency must be imported lazily at the call site inside the relevant adapter method, guarded if necessary with a try/except `ImportError` that raises a clear `RuntimeError`.
- **Error handling**: raise specific exception types; never silence exceptions with a bare `except: pass`. Catch-and-log is acceptable at the pipeline orchestrator boundary.
- **Logging rules**:
  - Use `logging.getLogger(__name__)` in every module; never the root logger directly.
  - Measurement values (heart rate numbers) must not appear in log messages at `INFO` level or above.
  - Secrets (`VOF_API_TOKEN`) must never appear in any log message at any level.
  - Connection events, validation rejections (without values), and startup/shutdown are appropriate at `INFO`.
  - Parsed payloads and raw bytes are appropriate at `DEBUG`.
- **Immutability**: domain objects (`VitalSign` subclasses, `ValidationResult`, `DeviceInfo`) are frozen dataclasses. Do not add mutable fields.
- **No global mutable state** outside `cli.py`. Module-level constants are fine; module-level instances are not.

## CI expectations

Every push and pull request must pass:
1. `ruff check .` — zero lint errors
2. `mypy src` — zero type errors (strict mode)
3. `pytest` (fast suite, no `hardware` marker) — all tests pass

Tests marked `hardware` are excluded from CI by default (they require physical devices). The `hardware` marker must be registered in `pytest.ini` or `pyproject.toml`.

CI does not run the server; do not write tests that depend on a running process.
