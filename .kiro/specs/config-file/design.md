# Design Document

**Spec: config-file** (`config.yaml` configuration layer — final phase-2 slice)

## Overview

This design adds a `config.yaml` configuration tier beneath the existing command-line-argument and
environment-variable sources, and introduces a single behavioral setting — `timezone` — that makes the
device-timestamp interpretation explicit and overridable. It adds no vital sign, adapter, FHIR mapper,
validator, store, sink, or API route. The change is confined to configuration wiring
(`config.py`, `cli.py`), one small threading of the new `timezone` value into the shared timestamp
decode path (`adapters/datetime_field.py` and its parser callers), a declared `pyyaml` dependency, and
documentation/example/ignore files.

Two user decisions taken after the first design draft are folded in here: (a) the config-file location
is **overridable on the command line** (`--config PATH`), defaulting to `config.yaml` at the repository
root; and (b) there are **no secret-specific guardrails in code** — configuration errors are surfaced
and **fail loud** at startup rather than being caught, scrubbed, or softened.

Two decisions drive the whole design and are settled up front here, because they were the open
questions coming out of requirements:

1. **YAML keys are Settings *field* names, not `VOF_`-prefixed env names.** A `config.yaml` sets
   `hr_min: 30`, `timezone: UTC`, `store_max: 5000` — the same identifiers as the `Settings` model
   fields. It does **not** use `VOF_HR_MIN`. This is what makes `extra = "forbid"` reject unknown YAML
   keys cleanly (they simply are not fields on the model) and keeps the YAML file readable. The `VOF_`
   prefix remains an *environment-variable* concern only.
2. **The precedence chain is CLI args → env (incl. `.env`) → `config.yaml` → defaults**, implemented by
   overriding `settings_customise_sources` and placing the YAML source *after* the env and dotenv
   sources in the returned tuple (first = highest priority). CLI args sit above `Settings` entirely:
   they are argparse values in `cli.py` that override the resolved setting per key, generalizing the
   existing `--adapter` pattern. This slice adds one new flag, `--config`, which selects *where* the
   YAML file is read from (it is not itself a `Settings` field); the per-key value overrides otherwise
   stay limited to the existing `--adapter`.

Grounded in the current code (read during design): `config.py`, `cli.py`,
`adapters/datetime_field.py`, `adapters/bp_parser.py`, `adapters/temp_parser.py`,
`adapters/weight_parser.py`, `adapters/plx_parser.py`, `adapters/parser.py`, and the adapter
`__init__.py` / `builtin/*` that construct parsers. Traceability: each section cites the
FR-CFG-\*/NFR-CFG-\* it satisfies, with a full mapping at the end. The existing heart-rate,
blood-pressure, oxygen-saturation, body-temperature, and body-weight suites (plus the
dependency-direction test) are the regression guardrail; with the config file absent and no
`timezone` override, behavior is byte-for-byte identical to the delivered `weight-body-mass` state.

### pydantic-settings facts this design relies on

The installed `pydantic-settings` is 2.15.0. The relevant, publicly documented behavior (rephrased for
licensing compliance; see the [pydantic-settings docs](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)):

- `settings_customise_sources(cls, init_settings, env_settings, dotenv_settings, file_secret_settings)`
  returns a tuple of source callables. The **first entry has the highest priority**; later entries fill
  only keys the earlier ones did not set.
- The library ships a `YamlConfigSettingsSource`, which reads a YAML file whose path is given by
  `yaml_file` in `model_config` (or passed explicitly to the source constructor). When the file does
  not exist, the source yields no values rather than erroring.
- `extra = "forbid"` is enforced against the merged result, so an unknown key from *any* source
  (env or YAML) fails validation at construction time.

*(Library facts rephrased for compliance; no code copied.)*

---

## Architecture

### Where the change sits

Configuration is already loaded exactly once in `cli.py` and passed explicitly to every component
(`tech.md` composition-root rule). This slice keeps that shape. The only structural additions are:

```
cli.py (composition root)
  |- argparse (parse_known first)       # resolve --config PATH before building Settings
  |- Settings(_yaml_path=cfg_path)      # layers YAML (at cfg_path) under env; adds `timezone`
  |    \- settings_customise_sources    # source ordering: env > dotenv > yaml
  |- argparse                           # CLI args override resolved settings per key (--adapter today)
  \- _resolve_adapter(..., settings)    # unchanged, but adapters now receive settings.timezone
        \- <Profile>BleAdapter
              \- <Profile>MeasurementParser(device_id, tz=..., now=...)
                    \- decode_timestamp(data, offset, tz)   # tz-aware decode, was host-local only
```

`--config` must be known *before* `Settings` is constructed, because it determines which YAML file the
YAML source reads. The composition root therefore resolves the config path first (a small argparse
pass), then constructs `Settings` with that path, then does the normal full argparse parse for
per-key overrides like `--adapter`. Default path: `config.yaml` at the repository root
(the process working directory, matching how `.env` is already resolved).

No package other than `config.py` (the model + sources) and `cli.py` (the path resolution and the
argparse override) touches the configuration machinery. `config.py` remains free of business-logic
imports, so `tests/test_dependency_directions.py` stays green (NFR-CFG-2).

### The two-part precedence: CLI above Settings, YAML below env

Precedence is enforced in two distinct places, because CLI args are not a `pydantic-settings` source:

- **Inside `Settings`** (env > dotenv > yaml > defaults) via `settings_customise_sources`.
- **In `cli.py`** (CLI args > everything in `Settings`) via argparse defaults sourced from the resolved
  `Settings`, so an explicitly supplied flag wins and an omitted flag falls through to the setting.
  Today only `--adapter` uses this (`default=settings.adapter`); the design documents the pattern as
  the general rule and leaves the existing single flag as the only instance in this slice (see
  "CLI-argument precedence" below).

---

## Components and Interfaces

### 1. `Settings` — YAML source wiring and the `timezone` field (`config.py`)

**FR-CFG-1, FR-CFG-2, FR-CFG-3, FR-CFG-4**

Add the `timezone` field and override `settings_customise_sources`. The YAML path is chosen by the
composition root and passed in at construction (FR-CFG-6); it defaults to `config.yaml` at the
repository root. Because the path is a runtime value (it can come from `--config`), the design uses the
documented pattern of passing an explicit `yaml_file` to `YamlConfigSettingsSource` inside
`settings_customise_sources`, reading the path from a private constructor kwarg stashed on the instance:

```python
from pathlib import Path
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

DEFAULT_CONFIG_PATH = Path("config.yaml")   # repo-root / working-directory default

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VOF_",
        extra="forbid",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # ... existing fields unchanged ...

    # Device-timestamp interpretation (FR-CFG-4). "local" preserves today's behavior.
    timezone: str = "local"

    def __init__(self, _yaml_path: Path | str = DEFAULT_CONFIG_PATH, **kwargs: object) -> None:
        # Stash the runtime YAML path for settings_customise_sources to read.
        self.__dict__["_yaml_path"] = Path(_yaml_path)
        super().__init__(**kwargs)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # First = highest priority. init (kwargs) > env > .env > config.yaml > field defaults.
        yaml_path = getattr(init_settings, "init_kwargs", {}).get("_yaml_path", DEFAULT_CONFIG_PATH)
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls, yaml_file=yaml_path),
        )
```

*(The exact seam for threading the runtime path into the source is finalized in tasks — pydantic-settings
supports both a `model_config["yaml_file"]` and a per-source `yaml_file=` argument; the design commits
to "the composition root chooses the path, `Settings` reads it," and the code above is the reference
shape. See the [pydantic-settings runtime-path discussion](https://github.com/pydantic/pydantic-settings/issues/259).)*

Key design points:

- **YAML keys are field names.** `YamlConfigSettingsSource` maps top-level YAML keys directly to model
  field names (`hr_min`, `timezone`, ...). Because the model is `extra = "forbid"`, an unknown YAML key
  raises a `ValidationError` at construction naming the offending field — satisfying FR-CFG-3 with no
  extra code. (This is the same mechanism that already rejects an unknown `VOF_*` env var.)
- **Env beats YAML per key.** `env_settings` and `dotenv_settings` precede the YAML source in the
  tuple, so a value present in the environment is used and the YAML value for that key is ignored;
  keys absent from the environment fall through to YAML, then to the field default (FR-CFG-2).
- **Absent file is a no-op.** `YamlConfigSettingsSource` yields nothing when the file is missing, so no
  error and no log line — FR-CFG-1. The composition root distinguishes an *explicitly requested but
  missing* path from the ordinary absent case (see section 4, FR-CFG-6).
- **Malformed YAML fails loudly.** A YAML parse error, or a top-level document that is not a mapping,
  surfaces as a startup exception identifying the file; `cli.py` lets it abort startup rather than
  falling back to defaults (FR-CFG-3). See section 4 for the wrapping that guarantees a clear message.
- **No secret guardrails in code.** `api_token` remains an ordinary field that any source can supply;
  the design adds **no** code that special-cases the token — no YAML-only ban, no scrubbing, no
  redaction pass, no catch-and-soften. The committed `config.yaml.example` omits `api_token` and the
  docs recommend keeping it in `.env`/env, but nothing in code enforces that. Configuration errors are
  surfaced and **fail loud** at startup (see Error Handling). The pre-existing rule "never *log*
  configuration values" (`security-privacy.md`) is untouched and is what keeps the token out of logs;
  this slice adds no new logging of config and no new secret-handling code. *(D4 records this choice.)*

### 2. `timezone` resolution — a small pure helper (`config.py`)

**FR-CFG-4**

`timezone` is a string. It must resolve to one of:

- `"local"` -> the host's local zone (today's behavior: `datetime.astimezone()` with no argument).
- an explicit zone name (`"UTC"`, `"America/Phoenix"`) -> a `zoneinfo.ZoneInfo` instance (stdlib, no
  new dependency).

Resolution and validation happen **once at startup**, not per reading. A pure function converts the
string to an `Optional[tzinfo]` (where `None` signals "use host local"), raising a clear `ValueError`
naming the invalid value if the string is neither `"local"` nor a resolvable `ZoneInfo`:

```python
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

def resolve_timezone(name: str) -> ZoneInfo | None:
    """Resolve a `timezone` setting to a tzinfo, or None for host-local."""
    if name == "local":
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Invalid timezone setting: {name!r}") from exc
```

Startup validation (FR-CFG-4 "fail at startup on an invalid value") is achieved via a pydantic
`field_validator` on `Settings.timezone` that calls `resolve_timezone`, so the invalid-value failure is
uniform with the unknown-key and malformed-YAML failures (all surface as `Settings()` construction
errors). The resolved `tzinfo` is then computed once and threaded to parsers.

### 3. `decode_timestamp` gains a timezone parameter (`adapters/datetime_field.py`)

**FR-CFG-4, NFR-CFG-1**

Today `decode_timestamp(data, offset)` hardcodes host-local (`naive.astimezone()`). The setting must
change *how the zoneless device timestamp is interpreted*. The change is additive and backward
compatible via a defaulted parameter:

```python
def decode_timestamp(
    data: bytes, offset: int, tz: tzinfo | None = None
) -> datetime | None:
    # ... decode year..second into the six ints, validate calendar ...
    try:
        naive = datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None
    if tz is None:
        return naive.astimezone()          # host local -- unchanged default behavior
    return naive.replace(tzinfo=tz)         # interpret the zoneless value AS being in tz
```

- **Semantics.** `tz=None` reproduces today's host-local behavior exactly (so every existing parser
  test that calls the two-argument form is unchanged). A non-`None` `tz` means "the device's wall-clock
  reading is in this zone" — `replace(tzinfo=tz)`, not `astimezone(tz)`, because the device timestamp is
  a naive wall-clock value, not an instant to be converted. This matches the requirement's wording:
  interpret the zoneless timestamp *as being in* the configured zone.
- **Signature stays additive** (NFR-CFG-1): the new parameter is keyword-defaulted, so `TIMESTAMP_SIZE`
  and the existing two-argument call sites keep compiling; no `__all__` name changes.

### 4. Threading `timezone` from `cli.py` to the parsers

**FR-CFG-4, FR-CFG-6**

The three parsers that decode an optional device timestamp — `BloodPressureMeasurementParser`,
`TemperatureMeasurementParser`, `WeightMeasurementParser` — each currently take `(device_id, now=...)`.
They gain a keyword `tz: tzinfo | None = None`, stored and passed through to `decode_timestamp`:

```python
def __init__(self, device_id: str, now=None, tz: tzinfo | None = None) -> None:
    self._device_id = device_id
    self._tz = tz
    self._now = now if now is not None else (lambda: datetime.now().astimezone())
    ...
# in parse():
effective = decode_timestamp(data, _TIMESTAMP_OFFSET, self._tz)
```

- **`plx_parser` and the heart-rate `parser`** carry no device timestamp, so they are **not** touched
  by the `tz` thread. (`plx_parser` imports the helper name but the Continuous Measurement
  characteristic has no timestamp field.)
- **Adapters** (`BloodPressureBleAdapter`, `HealthThermometerBleAdapter`, `WeightScaleBleAdapter`)
  gain an optional `tz` they forward to the parser they construct; `cli._resolve_adapter` passes
  `resolve_timezone(settings.timezone)` when building them. The mock adapters do not decode device
  timestamps, so they are unaffected.
- **`now` default vs `tz`.** The `now` fallback (used when a payload carries *no* timestamp) stays
  host-local-aware and is explicitly **out of scope** for the `timezone` setting per FR-CFG-4 ("SHALL
  NOT change the behavior of readings that carry no device timestamp"). Only the *device-supplied*
  timestamp path consults `tz`.

**Config path resolution (FR-CFG-6).** `cli.py` owns the YAML path:

- **Default.** With no `--config`, the path is `config.yaml` at the repository root (the process
  working directory, the same base `.env` already uses). If that default file is absent, the YAML
  source contributes nothing — the ordinary no-op case (FR-CFG-1). This is *not* an error.
- **Override.** `--config PATH` selects a different file. Because the path must be known before
  `Settings` is built, the composition root does a small `parse_known_args` pass to read `--config`
  first, then constructs `Settings(_yaml_path=path)`, then parses the remaining args for per-key
  overrides.
- **Explicitly requested but missing = fail loud.** When `--config PATH` is given and `PATH` does not
  exist, `cli.py` raises a clear startup error naming the path and aborts — distinct from the
  default-absent no-op. This is checked in the composition root (an explicit `Path.exists()` test on
  the user-supplied path) rather than relying on the YAML source's silent-when-missing behavior, so an
  explicit typo fails fast instead of silently loading defaults.

No `VOF_CONFIG_FILE` env var is added; the file location is a command-line concern only, keeping the
env surface unchanged. (An env var for the path can be added later additively if wanted.)

### 5. CLI-argument precedence (`cli.py`)

**FR-CFG-2**

The existing pattern is the whole mechanism: `parser.add_argument("--adapter", default=settings.adapter)`
means an explicit `--adapter X` wins over env/YAML/default, while an omitted flag falls through to the
resolved setting. The design **documents this as the general per-key rule** and keeps `--adapter` as the
only *per-key value* override in this slice. The one new flag, `--config`, is a different kind of flag:
it selects the YAML file location (§4), not the value of a `Settings` field, so it does not participate
in the per-key precedence chain — it decides which file the YAML tier reads. Adding more per-key
`--flag` overrides later is additive and needs no config change.

### 6. Dependency, example, and ignore files

**FR-CFG-5, NFR-CFG-4**

- **`pyproject.toml`**: add `pyyaml` as a direct dependency. It is already present transitively
  (via `uvicorn[standard]`), but `YamlConfigSettingsSource` needs it and this slice imports YAML
  handling, so it becomes a declared direct dependency (pinned per `tech.md`).
- **`config.yaml.example`** (committed, SPDX header as a YAML comment): lists the YAML-expressible
  settings by field name with a comment, **omitting `api_token`** and noting in a comment that the
  token belongs in `.env`/env. This is a documentation choice, not a code guardrail (D4) — the token
  is technically a valid field. The example also documents the precedence order, the `--config` flag,
  and the `timezone` key. Mirrors the role of `.env.example`.
- **`.env.example`**: add `VOF_TIMEZONE=local` with a comment describing the default and override.
- **`.gitignore`**: add `config.yaml` (the runtime file) so a populated config is not committed,
  mirroring how `.env` is ignored while `.env.example` is tracked.

---

## Data Models

No domain data model changes. The only model change is `Settings` gaining a `timezone: str = "local"`
field and the `settings_customise_sources` override. `VitalSign` and its subclasses, `Observation`
construction, and every ABC are untouched (NFR-CFG-1).

The `timezone` value space:

| Value | Meaning | Resolves to |
|-------|---------|-------------|
| `local` (default) | host local time | `None` -> `datetime.astimezone()` |
| `UTC` | UTC | `ZoneInfo("UTC")` |
| IANA name (e.g. `America/Phoenix`) | that zone | `ZoneInfo(name)` |
| anything else | error | `ValueError` at startup (FR-CFG-4) |

---

## Error Handling

**FR-CFG-3, FR-CFG-4, NFR-CFG-3**

**Fail loud, no soften.** Every configuration failure aborts startup by propagating; `cli.py` does
**not** catch, scrub, retry, or fall back to defaults. There are four failure classes:

- **Explicit `--config` path missing**: `cli.py` raises before building `Settings`, naming the path
  (§4). Fast and unambiguous.
- **Unknown key** (env or YAML): pydantic `ValidationError` naming the extra field (`extra="forbid"`),
  raised during `Settings()`.
- **Malformed / non-mapping YAML**: `YamlConfigSettingsSource` raises while loading during `Settings()`;
  startup aborts, no silent fallback.
- **Invalid `timezone`**: `field_validator` on `Settings.timezone` raises a `ValueError` naming the bad
  value.

All four propagate out of the composition root and stop the process with a non-zero exit and the
underlying error text — the operator sees exactly what is wrong.

**Interaction with the secret rule (NFR-CFG-3), given "no secret guardrails."** This slice adds no
token-specific handling and no scrubbing. The only secret protection is the *pre-existing* rule that
configuration values are never logged, which this slice does not weaken (it adds no logging of config).
Note that a pydantic `ValidationError` can include the offending value in its message — but only for the
field that actually failed. So `api_token` would appear in an error message *only* if the token field
itself is the thing that failed validation (e.g. wrong type), which is a legitimate loud startup failure
the operator must see, not a leak through an unrelated key. Errors for other keys name that key/path/zone
value, not the token, because the config is never dumped wholesale. This is consistent with "fail loud"
and with "never log the token": failing loudly to the operator's console at startup is not logging, and
we neither add a config dump nor suppress the real error.

---

## Testing Strategy

**NFR-CFG-5, NFR-CFG-6**

All fast, no hardware. New tests live in `tests/` mirroring the source layout (a `test_config.py` for
the source/precedence/timezone-validation behavior, and additions to the existing
`datetime_field`/parser tests for the `tz` parameter):

1. **Absent config file** -> `Settings()` equals env/default-only behavior; no error, no warning.
2. **YAML supplies a value** (e.g. `hr_min: 30`) -> the field reflects it when the env var is unset.
3. **Env beats YAML** -> with both `VOF_HR_MIN=40` and `hr_min: 30` in YAML, the field is `40`.
4. **CLI beats env and YAML** -> `--adapter miband10` wins over `VOF_ADAPTER`/YAML `adapter` (exercises
   the argparse override path in `cli.py`).
4a. **`--config PATH` selects the file** -> a YAML at a non-default path is loaded when `--config`
    points at it (and the default `config.yaml` is *not* read).
4b. **`--config PATH` missing = fail loud** -> an explicit `--config` to a non-existent path raises a
    startup error naming the path, distinct from the default-absent no-op (case 1).
5. **Unknown YAML key** (e.g. `bogus: 1`) -> `Settings()` raises, message names `bogus`.
6. **Malformed YAML** (unparseable, or a top-level list) -> `Settings()` raises, message names the file.
7. **`timezone` default `local`** -> `decode_timestamp(data, offset)` (tz=None) reproduces the existing
   host-local tz-aware result (regression parity with current parser tests).
8. **Explicit `timezone` (`UTC`)** -> `decode_timestamp(data, offset, ZoneInfo("UTC"))` returns the same
   wall-clock fields with UTC offset; a parser constructed with `tz=ZoneInfo("UTC")` yields a UTC-aware
   `effective`.
9. **Invalid `timezone`** (e.g. `Mars/Olympus`) -> `Settings(timezone=...)` raises naming the value.
10. **No-timestamp path unchanged** -> a payload without a device timestamp still uses the host-local
    `now()` fallback regardless of `tz` (guards the FR-CFG-4 "no-timestamp readings unchanged" clause).

Regression guardrail: the heart-rate, blood-pressure, oxygen-saturation, body-temperature, and
body-weight suites plus `tests/test_dependency_directions.py` stay green. The `decode_timestamp`
two-argument call sites are unchanged, so their existing tests pass without edit (the new `tz` param is
defaulted).

Secret/logging test (NFR-CFG-3): assert no config value is logged at any level by the new code path
(the pre-existing "never log config" rule). Per the "no secret guardrails" decision, there is **no**
test asserting the token is scrubbed from error text — the design adds no such scrubbing; a token-field
validation failure legitimately names the field. The test scope is limited to confirming the new
configuration code adds no logging of config values.

---

## Design decisions and rejected alternatives

- **D1 — YAML keys are field names, not `VOF_`-prefixed.** *Chosen.* It makes `extra="forbid"` do the
  unknown-key rejection for free, keeps YAML readable, and matches `YamlConfigSettingsSource`'s default
  mapping. *Rejected:* prefixed YAML keys (`VOF_HR_MIN:`), which would need a custom key-stripping
  source and reads awkwardly in a nested file — the whole point of moving to YAML.
- **D2 — `replace(tzinfo=tz)`, not `astimezone(tz)`, for a configured zone.** *Chosen.* The device
  timestamp is a zoneless wall-clock value; the setting says which zone that wall clock is in.
  `astimezone(tz)` would wrongly treat the naive value as already-UTC and shift it. *Rejected:*
  `astimezone`, which corrupts the very timestamps the feature is meant to interpret correctly.
- **D3 — `timezone` validated at `Settings()` construction (field_validator).** *Chosen.* Uniform with
  unknown-key and malformed-YAML failures; one startup failure surface. *Rejected:* validating lazily
  at first decode, which would let a bad config start the server and fail only when a device connects.
- **D4 — No secret guardrails in code; fail loud (user decision).** *Chosen.* The design adds no
  token-specific code — no YAML-only ban, no scrubbing, no redaction, no catch-and-soften.
  Configuration errors propagate and abort startup with their real messages. The only secret protection
  is the pre-existing "never log config values" rule, which is not weakened. *Rejected:* a runtime
  refusal of `api_token` in YAML (special-cases one field, softens a real failure) and any error-text
  scrubbing (hides the very information a loud failure is meant to surface). Consequence: if an operator
  puts the token in YAML it will work; the docs recommend against it and the example omits it, but code
  does not enforce it — matching the explicit "no secret guardrails" instruction.
- **D5 — `--config PATH` override; default `config.yaml` at repo root (user decision).** *Chosen.* The
  file location is command-line-selectable; the default is `config.yaml` in the working directory
  (repo root). An explicit `--config` to a missing path fails loud at startup; a missing *default* file
  is the ordinary no-op. Path is resolved by a small `parse_known_args` pass before `Settings` is built.
  *Rejected:* a fixed non-overridable path (the earlier draft), and a `VOF_CONFIG_FILE` env var (keeps
  the env surface unchanged; can be added later if wanted).
- **D6 — CLI value-override precedence via the existing `--adapter` pattern; `--config` is a
  path selector, not a value override.** *Chosen.* Per-key value overrides stay limited to `--adapter`;
  `--config` selects the YAML file rather than a field value, so it sits outside the per-key precedence
  chain. *Rejected:* adding `--host`, `--port`, etc. now — additive later, out of scope here.

## Open items

None. The two prior open items (explicit config path; secret-guardrail stance) are resolved by the
user decisions recorded in D4 and D5.

---

## Requirements traceability

| Requirement | Design coverage |
|-------------|-----------------|
| FR-CFG-1 (YAML source; file optional, layer permanent) | Section 1 (source always in tuple; absent file no-op), Overview |
| FR-CFG-2 (CLI > env > yaml > defaults) | Section 1 (source ordering), Section 5 (CLI override), Architecture two-part precedence |
| FR-CFG-3 (unknown-key + malformed rejected) | Section 1 (extra=forbid on field-name keys), Error Handling (fail loud, no soften) |
| FR-CFG-4 (timezone setting) | Section 1 (field), Section 2 (resolve/validate), Section 3 (decode_timestamp tz), Section 4 (threading) |
| FR-CFG-5 (example, no committed secret, ignore) | Section 6 (config.yaml.example omits token by convention, .env.example, .gitignore); D4 (no code guardrail) |
| FR-CFG-6 (config path resolution) | Section 4 (`--config` override + default `config.yaml` at repo root + explicit-missing fail-loud), Architecture (parse_known first), D5 |
| NFR-CFG-1 (no breaking changes) | Section 1/Section 3 additive field + defaulted param; no ABC/__all__ change |
| NFR-CFG-2 (dependency directions) | Architecture (only config.py/cli.py touch config machinery) |
| NFR-CFG-3 (secret/logging discipline) | Error Handling (no config logging; errors name keys/paths) |
| NFR-CFG-4 (provenance/licensing) | Section 6 (SPDX headers, pyyaml pinned; no ported code) |
| NFR-CFG-5 (test coverage) | Testing Strategy (10 cases + regression guardrail) |
| NFR-CFG-6 (docs/traceability) | Section 6 + CHANGELOG entry (tasks); cites both briefs |
