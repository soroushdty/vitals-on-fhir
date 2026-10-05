# Implementation Plan

**Spec: config-file** (`config.yaml` configuration layer — final phase-2 slice)

Each task is small, verifiable, and traces to requirements. This slice touches **no** vital-sign,
adapter-lifecycle, FHIR-mapper, validator, store, sink, or API code. Its surface is: the `Settings`
model and a timezone helper (`config.py`), the shared `decode_timestamp` helper and the three parsers
that call it with a device timestamp (`adapters/`), the composition root (`cli.py`), a declared
`pyyaml` dependency, and example/ignore/doc files. Order: add the YAML source + `timezone` field and
its validation, then the additive `decode_timestamp` parameter and the parser/adapter threading, then
the CLI `--config` resolution and per-key precedence, then dependency/example/ignore files, then tests,
then docs + changelog + full verification.

After every task run `uv run ruff check .`, `uv run mypy src`, and `uv run pytest`; the existing
heart-rate, blood-pressure, oxygen-saturation, body-temperature, and body-weight suites plus
`tests/test_dependency_directions.py` must stay green throughout (NFR-CFG-1, NFR-CFG-2, NFR-CFG-5).
Every new source file starts with `# SPDX-License-Identifier: AGPL-3.0-or-later` (NFR-CFG-4). Test
sub-tasks are marked `*` (optional). The design has **no** Correctness Properties section, so tests are
the concrete example cases enumerated in the design's Testing Strategy (design §Testing Strategy),
extending the existing `tests/test_config.py` and the existing parser/`datetime_field` tests. No test
may start or connect to a running server, and no non-`hardware` test may import `bleak`.

**Regression invariant (the whole point of the additive design):** with no `config.yaml` file present
and no `VOF_TIMEZONE`/`timezone` set, every existing test passes unchanged, because the YAML source
contributes nothing and `decode_timestamp`'s new `tz` parameter defaults to the prior host-local
behavior.

- [x] 1. Add the `config.yaml` source and the `timezone` field to `Settings`
  - In `config.py`: add `pyyaml`-backed YAML wiring by overriding `settings_customise_sources` to
    return `(init_settings, env_settings, dotenv_settings, YamlConfigSettingsSource(cls, yaml_file=...))`
    — YAML strictly below env/dotenv, above field defaults (FR-CFG-2). Keep `extra="forbid"`,
    `env_prefix="VOF_"`, and the existing `.env` support unchanged (FR-CFG-1, FR-CFG-3).
  - Accept the runtime YAML path from the composition root: add a `DEFAULT_CONFIG_PATH =
    Path("config.yaml")` module constant and thread the chosen path into the source (per design §1 —
    the private `_yaml_path` constructor seam, or the equivalent `model_config["yaml_file"]` set by the
    composition root; finalize whichever mypy-strict-clean form pydantic-settings 2.15 accepts). YAML
    keys are Settings **field names** (`hr_min`, `timezone`, ...), not `VOF_`-prefixed (design D1).
  - Add the `timezone: str = "local"` field with a comment that `local` preserves today's host-local
    behavior (FR-CFG-4). Add a `resolve_timezone(name) -> ZoneInfo | None` pure helper (stdlib
    `zoneinfo`; `None` means host-local) and a pydantic `field_validator` on `timezone` that calls it,
    so an invalid zone fails at `Settings()` construction naming the value (FR-CFG-4, design §2, §3).
  - Do not add any secret-handling code (no `api_token` special-casing, no scrubbing) — configuration
    errors propagate unmodified (FR-CFG-5, NFR-CFG-3, design D4). Add no logging of config values.
  - `config.py` stays free of business-logic/cross-package imports (NFR-CFG-2).
  - _Design: §1, §2, Data Models, D1, D3, D4. Requirements: FR-CFG-1, FR-CFG-2, FR-CFG-3, FR-CFG-4, NFR-CFG-1, NFR-CFG-2, NFR-CFG-3_

  - [x] 1.1 `Settings` YAML + precedence + timezone tests (extend `tests/test_config.py`)
    - Reuse the existing `_clean_vof_env` autouse fixture, `_write_env`, `tmp_path`, and
      `monkeypatch.chdir` helpers. Add a small `_write_yaml(dir, contents)` helper writing `config.yaml`.
    - Cases (design Testing Strategy 1–3, 5–6): absent `config.yaml` → identical to env/default-only,
      no error; a `config.yaml` `hr_min: 30` reflected when the env var is unset; `VOF_HR_MIN=40` +
      YAML `hr_min: 30` → field is `40.0` (env beats YAML); unknown YAML key `bogus: 1` → `Settings()`
      raises naming `bogus`; malformed YAML (unparseable, and a top-level list) → `Settings()` raises
      identifying the file.
    - Timezone cases (design Testing Strategy 9): `timezone` default is `"local"`; a valid explicit zone
      (`UTC`, `America/Phoenix`) constructs; an invalid zone (`Mars/Olympus`) → `Settings()` raises
      naming the value. `resolve_timezone("local")` returns `None`; `resolve_timezone("UTC")` returns a
      `ZoneInfo`.
    - _Design: §1, §2. Requirements: FR-CFG-1, FR-CFG-2, FR-CFG-3, FR-CFG-4, NFR-CFG-5_

- [x] 2. Add the timezone parameter to the shared `decode_timestamp` helper
  - In `adapters/datetime_field.py`: add a keyword-defaulted `tz: tzinfo | None = None` parameter to
    `decode_timestamp(data, offset, tz=None)`. `tz is None` keeps the current `naive.astimezone()`
    host-local behavior byte-for-byte; a non-`None` `tz` returns `naive.replace(tzinfo=tz)` — interpret
    the zoneless device wall-clock **as being in** that zone, not `astimezone(tz)` (design D2).
    `TIMESTAMP_SIZE` and the `None`-on-invalid-calendar behavior are unchanged. No `__all__` change.
  - Additive only: existing two-argument callers keep compiling (NFR-CFG-1).
  - _Design: §3, D2. Requirements: FR-CFG-4, NFR-CFG-1_

  - [x] 2.1 `decode_timestamp` tz tests (extend the existing datetime_field tests)
    - `tz=None` reproduces the existing host-local tz-aware result for a known payload (regression
      parity, design Testing Strategy 7). `tz=ZoneInfo("UTC")` yields the same wall-clock fields with a
      UTC offset (design Testing Strategy 8). An invalid-calendar payload still returns `None`
      regardless of `tz`.
    - _Design: §3. Requirements: FR-CFG-4, NFR-CFG-5_

- [x] 3. Thread `timezone` through the timestamp-decoding parsers and their adapters
  - Add a keyword `tz: tzinfo | None = None` to `BloodPressureMeasurementParser`,
    `TemperatureMeasurementParser`, and `WeightMeasurementParser` constructors; store it and pass it as
    the third argument to `decode_timestamp(...)` at the device-timestamp call site. Leave the
    `now()` fallback (no-device-timestamp path) host-local-aware and untouched (FR-CFG-4 explicitly does
    not change no-timestamp readings). Do **not** touch `plx_parser` or the heart-rate `parser` (no
    device timestamp).
  - Give `BloodPressureBleAdapter`, `HealthThermometerBleAdapter`, and `WeightScaleBleAdapter` an
    optional `tz` they forward to the parser they build. Mock adapters are unaffected (they emit
    `now()`-based readings, no device-timestamp decode).
  - No ABC signature or `__all__` name changes; all additions are keyword-defaulted (NFR-CFG-1).
  - _Design: §4. Requirements: FR-CFG-4, NFR-CFG-1_

  - [x] 3.1 Parser timezone threading + no-timestamp-unchanged tests
    - A parser built with `tz=ZoneInfo("UTC")` parsing a timestamp-present payload yields a UTC-aware
      `effective` matching the device wall-clock (one parser is sufficient; the three share the helper).
    - No-timestamp path unchanged (design Testing Strategy 10): a timestamp-absent payload still uses the
      host-local `now()` fallback regardless of `tz`.
    - _Design: §3, §4. Requirements: FR-CFG-4, NFR-CFG-5_

- [x] 4. Resolve the config path and wire precedence in the composition root
  - In `cli.py`: add a `--config PATH` argument. Because the path must be known before `Settings` is
    built, do a small `parse_known_args` pass to read `--config` first, then construct
    `Settings(_yaml_path=path)` (default `config.yaml` at the working directory / repo root), then run
    the full argparse parse for per-key overrides (FR-CFG-6, design §4, Architecture).
  - Explicit-missing = fail loud: if `--config PATH` is given and `PATH` does not exist, raise a clear
    startup error naming the path and abort — distinct from the absent-*default* no-op, which stays
    silent (FR-CFG-6, design §4). Do not catch/soften any `Settings()` construction error; let unknown
    key / malformed YAML / invalid timezone propagate and stop startup (FR-CFG-3, FR-CFG-4, NFR-CFG-3,
    design Error Handling).
  - Compute the resolved `tzinfo` once via `resolve_timezone(settings.timezone)` and pass it to the
    device adapters built in `_resolve_adapter` (design §4). Keep the existing `--adapter` per-key
    override as the general precedence pattern; `--config` is a file-location selector, not a value
    override (FR-CFG-2, design §5, D6). No `VOF_CONFIG_FILE` env var is added.
  - _Design: §4, §5, Architecture, D5, D6. Requirements: FR-CFG-2, FR-CFG-6, NFR-CFG-3_

  - [x] 4.1 CLI precedence + `--config` resolution tests
    - CLI beats env and YAML (design Testing Strategy 4): `--adapter miband10` wins over a conflicting
      `VOF_ADAPTER`/YAML `adapter` (test the resolution helper; no running server).
    - `--config PATH` selects a non-default file (design Testing Strategy 4a): a YAML at a non-default
      path is loaded and the default `config.yaml` is not read.
    - `--config PATH` missing fails loud (design Testing Strategy 4b): a non-existent explicit path
      raises a startup error naming the path, distinct from the absent-default no-op.
    - These test the composition-root helpers directly; `cli.py` is exempt from full coverage but the
      path-resolution and precedence helpers are unit-tested. No server is started.
    - _Design: §4, §5. Requirements: FR-CFG-2, FR-CFG-6, NFR-CFG-5_

- [x] 5. Declare the dependency and add the example + ignore files
  - `pyproject.toml`: add `pyyaml` as a pinned direct dependency (already transitive via
    `uvicorn[standard]`, now declared because `YamlConfigSettingsSource` needs it) (NFR-CFG-4).
    Run `uv sync` / `uv lock` as needed so the lockfile is consistent.
  - Create committed `config.yaml.example` (SPDX header as a YAML comment): list the YAML-expressible
    settings by **field name** with comments, documenting the precedence order, the `--config` flag,
    and the `timezone` key with its `local` default. **Omit `api_token`** and note in a comment that the
    token belongs in `.env`/env — a documentation convention, not a code guardrail (FR-CFG-5, D4).
  - `.env.example`: add `VOF_TIMEZONE=local` with a comment describing the default and the override.
  - `.gitignore`: add `config.yaml` (the runtime file) so a populated config is not committed, mirroring
    how `.env` is ignored while `.env.example` is tracked (FR-CFG-5).
  - _Design: §6, D4. Requirements: FR-CFG-5, NFR-CFG-4_

- [x] 6. Docs, changelog, brief update, and full verification
  - Update `docs/brief-config-file.md` if any wording in the already-added **Promotion** section needs
    to match the final `--config` / no-guardrail decisions (the section already records the promotion;
    ensure it names the `--config` override and the fail-loud, no-secret-guardrail stance) (NFR-CFG-6).
  - Prepend a `CHANGELOG.md` entry recording: the new `config.yaml` configuration source (permanent
    layer, file optional) wired via `settings_customise_sources`; the CLI-args → env → `config.yaml` →
    defaults precedence; the `--config PATH` flag (default `config.yaml` at repo root; explicit-missing
    fails loud); the `timezone` / `VOF_TIMEZONE` key (default `local`) and the additive
    `decode_timestamp(tz=...)` parameter; `pyyaml` promoted to a direct dependency; and the
    `config.yaml.example` / `.gitignore` additions. Reference the FR-CFG-*/NFR-CFG-* IDs and note this
    closes phase 2. If any EviTrace-ported pattern is used, record it in `NOTICE` (NFR-CFG-4, NFR-CFG-6).
  - Run `uv run ruff check .`, `uv run mypy src`, and `uv run pytest` — all green, including
    `tests/test_dependency_directions.py` and every existing vital-sign suite. Confirm the regression
    invariant: with no `config.yaml` and no `VOF_TIMEZONE`, existing behavior is unchanged.
  - Scripted no-server smoke (optional, no hardware): `uv run vitals-on-fhir --adapter mock` starts and
    a `config.yaml` with a benign key (e.g. `port`) is honored below a conflicting env var. Do not add
    tests that depend on a running server.
  - _Design: §Overview, §6, Error Handling, Requirements traceability. Requirements: NFR-CFG-1, NFR-CFG-2, NFR-CFG-3, NFR-CFG-4, NFR-CFG-5, NFR-CFG-6_

## Notes

- Tasks marked `*` are optional test sub-tasks; core implementation sub-tasks are never optional.
- The design has no Correctness Properties section, so there are no Hypothesis property tasks; tests are
  the concrete example cases from the design's Testing Strategy (1–10), added to the existing
  `tests/test_config.py` and the existing parser/`datetime_field` tests.
- Regression guardrail: the additive `decode_timestamp(tz=None)` default and the always-present-but-
  empty-when-absent YAML source mean every existing suite must stay green with zero edits.
- Per the user decision, there are **no** secret guardrails in code and configuration errors fail loud;
  no task adds token special-casing, scrubbing, or catch-and-soften.
- `cli.py` is exempt from full unit-test coverage (composition root); its path-resolution and
  precedence helpers are unit-tested via task 4.1 without starting a server.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "2"] },
    { "id": 1, "tasks": ["1.1", "2.1", "3"] },
    { "id": 2, "tasks": ["3.1", "4", "5"] },
    { "id": 3, "tasks": ["4.1", "6"] }
  ]
}
```
