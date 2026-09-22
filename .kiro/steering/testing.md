---
inclusion: fileMatch
fileMatchPattern: "tests/**"
---

# Testing — vitals-on-fhir

## Strategy

- Tests live in `tests/`, mirroring `src/vitals_on_fhir/`. A test for `vitals/builtin/heart_rate.py` goes in `tests/vitals/test_heart_rate.py`.
- The fast suite (`uv run pytest`) runs without hardware and without a running server. It must pass in CI.
- Tests needing a real BLE device carry the `hardware` pytest marker and are excluded from CI by default.
- Do not write tests that start or connect to a live server process.
- Do not automatically add tests beyond what a spec explicitly requests — but every concrete class and every ABC must have at minimum the coverage items described below.

## `MockAdapter` as the default test double

- Use `MockAdapter` (from `adapters/builtin/`) as the default stand-in for a real device in all pipeline, store, API, and dashboard tests.
- `MockAdapter` must be configurable to emit: valid readings, implausible values (outside `plausible_range`), and readings where `sensor_contact=False`. Tests that exercise the validator chain must use these modes explicitly.
- Never instantiate `BleHeartRateAdapter` or `MiBand10Adapter` in the fast test suite. Do not import `bleak` in any test file that lacks the `hardware` marker.

## Dependency-direction test

`tests/test_dependency_directions.py` is an AST-based test that parses every `.py` module under `src/vitals_on_fhir/` and checks for forbidden cross-package imports.

Structure requirements:
- One `pytest.mark.parametrize` case per forbidden direction from the table in `structure.md`.
- One combined test that fails if any forbidden import exists anywhere.
- Uses Python's `ast` module; no runtime imports of the modules under test.
- Must run in under 2 seconds on a modern laptop.

Run after any cross-package import change: `uv run pytest tests/test_dependency_directions.py`.

This test is ported from EviTrace — see `NOTICE` and the file header comment.

## ABC contract tests

### Rule: no ABC may be instantiated directly

For every ABC in the project (`VitalSign`, `ScalarVital`, `ComponentVital`, `DeviceAdapter`, `GattCharacteristicParser`, `BleHeartRateAdapter`, `Validator`, `VitalMapper`, `ObservationSink`, `ObservationStore`, `Authenticator`), assert that attempting direct instantiation raises `TypeError`.

### Rule: every concrete adapter passes the `DeviceAdapter` contract suite

Provide a reusable parametrized suite in `tests/adapters/contract.py` (or `conftest.py`). The suite asserts:
- The class is a concrete subclass of `DeviceAdapter` (no unimplemented abstract methods).
- `supported_vitals` is a non-empty tuple of `VitalSign` subclasses.
- `device_info` returns a `DeviceInfo` instance.
- `state` returns a `ConnectionState` value.
- `vitals()` returns an async iterator.
- The class does not import `bleak` at module level (AST check; skip for `hardware`-marked adapters).

`MockAdapter` must pass this suite. Third-party adapters can import and run it from their own test suites.

### Rule: every concrete vital-sign class has valid metadata

For every concrete `VitalSign` subclass (`HeartRate` in the MVP), assert:
- `loinc_code` is a non-empty string.
- `us_core_profile` starts with `"http://hl7.org/fhir/"`.
- If `ScalarVital`: `ucum_unit` is a non-empty string, `plausible_range` is a `(float, float)` with `range[0] < range[1]`.
- The class can be instantiated with minimal valid arguments without raising.

## Hypothesis property tests for the payload parser

Target: `HeartRateMeasurementParser` and the pure parsing functions in `adapters/parser.py`.

### Test 1 — never crashes on arbitrary bytes

```python
@given(st.binary())
def test_parser_never_crashes(data: bytes) -> None:
    result = HeartRateMeasurementParser().parse(data)
    assert result is None or isinstance(result, HeartRate)
```

This test must pass for all inputs, including empty bytes, single bytes, and very long byte strings.

### Test 2 — round-trips valid payloads

Build valid Heart Rate Measurement payloads programmatically (uint8 and uint16 value formats, with and without sensor contact, with and without energy expended, with and without RR intervals). Assert that parsing them produces the expected `HeartRate` with the correct `value` and `sensor_contact`.

Use `st.builds` or explicit strategies over the valid field combinations rather than pure random bytes for this test.

## Fixtures for Heart Rate Measurement payloads

Provide the following as `pytest` fixtures or module-level constants in `tests/adapters/conftest.py`:

| Fixture name | Description |
|-------------|-------------|
| `hr_payload_uint8_contact` | Valid payload, uint8 HR value, sensor contact present |
| `hr_payload_uint8_no_contact` | Valid payload, uint8 HR value, sensor contact bit = false |
| `hr_payload_uint16_contact` | Valid payload, uint16 HR value, sensor contact present |
| `hr_payload_uint16_no_contact` | Valid payload, uint16 HR value, sensor contact bit = false |
| `hr_payload_with_rr` | Valid payload with RR intervals included |
| `hr_payload_truncated` | Truncated payload (too few bytes for the declared format) |
| `hr_payload_empty` | Zero-length bytes |

For each valid fixture, assert the parser produces a `HeartRate` with the expected `value` and `sensor_contact`. For truncated and empty, assert the parser returns `None`.

## FHIR validation assertions

When a test produces an `Observation`, assert:
- `resourceType == "Observation"`
- `status == "final"`
- `code.coding[0].code` matches the expected LOINC code
- `category[0].coding[0].code == "vital-signs"`
- `meta.profile` contains the expected US Core profile URL
- `effectiveDateTime` and `issued` are both present and parseable as ISO 8601
- `valueQuantity.system == "http://unitsofmeasure.org"`
- `valueQuantity.code` matches the expected UCUM unit

Do not re-implement FHIR validation — use `fhir.resources` model construction as the validation mechanism (construction raises on invalid resources).

## API authentication tests

In `tests/api/`, include at minimum:
- Request with no `Authorization` header → 401 with `OperationOutcome`
- Request with `Authorization: Bearer wrong-token` → 401 with `OperationOutcome`
- Request with correct token → 200 (or appropriate success code)
- WebSocket upgrade with no token → connection refused or 401
- WebSocket upgrade with correct token → connection accepted

Use `httpx.AsyncClient` with FastAPI's `TestClient` or `AsyncClient`; do not start a live server.

## `hardware` marker

- Register the marker in `pyproject.toml` under `[tool.pytest.ini_options]`:
  ```toml
  markers = ["hardware: requires a physical BLE device (deselected in CI)"]
  ```
- Default deselection: add `-m "not hardware"` to `addopts` in `pyproject.toml` so `uv run pytest` skips hardware tests automatically.
- Hardware tests live alongside their unit-test counterparts in the same `tests/<package>/` directory, named `test_*_hardware.py` or decorated with `@pytest.mark.hardware`.

## Coverage expectations

- The fast suite must achieve meaningful coverage of the validator chain, the parser (all flag combinations), the mapper, the store, and the API auth layer.
- Coverage is not enforced as a hard gate in CI in the MVP, but do not add code paths that are untestable without hardware.
- `cli.py` (the composition root) is exempt from unit-test coverage requirements; it is tested implicitly by integration/smoke tests.
