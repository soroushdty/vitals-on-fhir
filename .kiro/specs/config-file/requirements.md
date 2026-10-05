# Requirements Document

**Spec: config-file** (`config.yaml` configuration layer — final phase-2 slice)

## Introduction

This spec is the fifth and final slice in roadmap phase 2 (home health devices). The four vital-sign
siblings — `home-health-devices` (blood pressure), `oxygen-saturation`, `body-temperature`, and
`weight-body-mass` — are delivered. This slice adds no new vital sign. Instead it promotes the
idea-only brief `docs/brief-config-file.md` into an implemented feature: a **`config.yaml`
configuration source layered under `pydantic-settings`**, sitting below command-line arguments and
environment variables (and `.env`) in authority.

A note on "optional": the brief called this an *optional* `config.yaml`. Once implemented, the
`config.yaml` **layer is not optional** — it is a permanent, always-present tier of the configuration
system's precedence chain. What is optional is only whether a `config.yaml` **file happens to exist on
disk** at runtime: if the file is absent, that tier simply contributes nothing (a no-op), exactly as
`.env` contributes nothing when no `.env` file exists. This spec says "the config file is absent" for
the file-on-disk case and never calls the layer itself optional.

The authority order, highest to lowest, is: **command-line arguments → environment variables (and
`.env`) → `config.yaml` → built-in defaults.** If a CLI argument and any lower source disagree on a
key, the CLI argument wins; if an environment variable and `config.yaml` disagree, the environment
variable wins.

The config file's *location* is command-line-selectable via `--config PATH`, defaulting to
`config.yaml` at the repository root. `--config` chooses which file the `config.yaml` tier reads; it is
not itself a per-key value override. An explicitly supplied `--config` path that does not exist fails
loudly at startup, whereas a missing *default* file is a silent no-op.

Folding this in as the last part of phase 2 is a deliberate promotion, not an automatic one. The
brief left the `config.yaml` idea idea-only after the phase-2 length-driver assessment closed
("not promoted on length"), and it recorded two other drivers that the length count alone did not
capture:

1. **The structural driver — independently affirmed.** Per-vital validation modes sketched in
   `docs/brief-validation-modes.md` (keyword modes, ±k·SD flagging bands, explicit per-person bounds)
   do not express as flat `VOF_<VITAL>_<BOUND>` pairs. Crucially, this conclusion is **independent
   corroboration**, not circular reasoning from the config brief itself: `brief-validation-modes.md`
   was authored during a *different* slice (`body-temperature`), for a *different* purpose (deciding
   how personal/clinical thresholds should work), and it reached the structural conclusion on its own
   — recording that the modes "ride on structured configuration" because "modes, k-factors, and
   per-person option sets do not express cleanly as flat `VOF_<VITAL>_<BOUND>` env pairs." Two
   separate work streams landing on "flat env pairs are the wrong *shape* for this" is the affirmation
   that settles the driver. That validation-mode work is still idea-only and is **not built here**;
   this slice provides only the nested-config *mechanism* it would later ride on.
2. **The timezone key** — the blood-pressure parser interprets a device's zoneless timestamp as host
   local time, a choice that is currently implicit. The brief named a `timezone` key (default `local`)
   as the concrete trigger for a config file. This slice makes that behavior explicit and
   configurable, which is the one behavioral change the config layer carries.

The two drivers answer different questions. The phase-2 assessment asked whether the flat list is too
**long** and answered no. The structural driver asks whether the flat list is the wrong **shape** for
planned work and — affirmed independently in `brief-validation-modes.md` — answers yes. "Not awkward
on length" and "the config layer is justified" are therefore not in tension; they address length and
structure separately, exactly as the brief asked future work to weigh them.

This slice therefore delivers the *mechanism* (a YAML source correctly layered under env vars) and the
*one behavioral key the brief called out* (`timezone`), while explicitly deferring the structural
validation-modes work to its own future spec. Every guardrail the brief set for "if this is ever
picked up" is a hard requirement here.

### What this slice adds and what it reuses

- **Adds** a `config.yaml` source wired into the existing `Settings` class via a `pydantic-settings`
  custom settings source, plus a `timezone` setting and its use in the device-timestamp decode path,
  plus a committed `config.yaml.example` and documentation. The source is always present; it
  contributes nothing when the file is absent.
- **Reuses** the existing `Settings` class, the CLI-argument override pattern already used for
  `--adapter`, the `VOF_` env prefix, the `.env` support, the `extra = "forbid"` rejection of unknown
  keys, and the single-load-in-`cli.py` composition-root discipline — none of which change in shape.
  The YAML source slots beneath CLI arguments and env vars in precedence.
- **Does not add** any per-vital validation mode, any `±k·SD` band, any keyword mode, any per-person
  bounds, or any nested per-vital range restructuring. The `VOF_<VITAL>_<BOUND>` range keys stay flat
  and authoritative; YAML may mirror them but does not restructure them in this slice.

### Relationship to the earlier slices

- **Introduces no new vital sign, adapter, parser, or FHIR mapper.** The `vitals`, `adapters`, `fhir`,
  `validation`, `pipeline`, `store`, `api`, and `dashboard` packages are untouched in shape.
- **Changes only the configuration surface** (`config.py`, `cli.py` composition root, and docs) plus
  the single timestamp-decode call site that consumes the new `timezone` setting.
- **Preserves store-and-forward and the local-time-implicit default:** with the config file absent and
  no `timezone` override, behavior is byte-for-byte identical to the delivered `weight-body-mass`
  state.

### Numbering

New functional (**FR-CFG-\***) and non-functional (**NFR-CFG-\***) requirement IDs are additive and
distinct from the four vital-sign siblings' `FR-HH-*`/`FR-SPO2-*`/`FR-TEMP-*`/`FR-WT-*` families and
their NFR counterparts. Existing MVP and phase-2 IDs are preserved and not renumbered, so traceability
stays unambiguous for the planned preprint. Acceptance criteria follow EARS patterns and INCOSE
quality rules, mirroring the sibling specs.

## Glossary

- **Pipeline**: the end-to-end vitals-on-fhir system (adapter → validators → mapper → sinks).
- **Settings**: the existing `pydantic-settings` `Settings` class in `config.py`, the single typed
  configuration object.
- **CLI_Args**: command-line arguments parsed in `cli.py` (e.g. `--adapter`). The highest-authority
  configuration source; a CLI argument overrides every lower source for the key it sets.
- **Env_Source**: the environment-variable configuration source (the `VOF_` prefix), including values
  supplied via `.env`. Sits below CLI_Args and above the Yaml_Source.
- **Yaml_Source**: the `config.yaml` configuration source added by this slice — a permanent tier of
  the precedence chain that contributes values when the config file exists and nothing when it is
  absent. The layer is always present; only the file on disk is optional.
- **Config_File**: the `config.yaml` file on disk, which may be present or absent at runtime.
- **Config_Path**: the filesystem path at which the CLI looks for the Config_File.
- **CLI**: `cli.py`, the composition root — the only module that loads Settings, parses CLI_Args, and
  instantiates concrete classes.
- **Timezone_Setting**: the new `timezone` configuration key (default `local`) governing how a
  device's zoneless timestamp is interpreted.
- **Local_Time_Default**: the current, implicit behavior of interpreting a device's zoneless timestamp
  as host local time and returning it timezone-aware.
- **Decode_Timestamp**: the shared `adapters/datetime_field.decode_timestamp` helper (and
  `TIMESTAMP_SIZE`) used by the blood-pressure, temperature, and weight parsers.
- **Range_Keys**: the flat per-vital plausibility bounds following the `VOF_<VITAL>_<BOUND>`
  convention (`VOF_HR_MIN/MAX`, `VOF_BP_SYSTOLIC_MIN/MAX`, `VOF_BP_DIASTOLIC_MIN/MAX`,
  `VOF_SPO2_MIN/MAX`, `VOF_TEMP_MIN/MAX`, `VOF_WEIGHT_MIN/MAX`).
- **Secret**: `VOF_API_TOKEN`, which must never appear in a committed file or in a log message. Per the
  user's "no secret guardrails, fail loud" decision, this slice adds no code that special-cases the
  token; configuration errors surface unmodified (see FR-CFG-5 and NFR-CFG-3).

---

## Requirements

### Functional requirements

#### FR-CFG-1 — YAML configuration source (file optional, layer permanent)
*Traces to `docs/brief-config-file.md`, product NFR-6, and `tech.md` (config discipline).*

- THE Pipeline SHALL add the Yaml_Source as a permanent configuration tier, layered into the existing
  Settings via a `pydantic-settings` custom settings source. The Yaml_Source SHALL always be part of
  the precedence chain; only the presence of the Config_File on disk is optional.
- WHERE the Config_File is absent, THE Yaml_Source SHALL contribute no values and THE Pipeline SHALL
  start and behave exactly as it does today with CLI arguments, environment variables, and `.env`
  only; the file's absence SHALL NOT be an error and SHALL emit no warning at `INFO` or above.
- THE Yaml_Source SHALL be additive: it SHALL NOT replace, remove, or alter the CLI_Args, the
  Env_Source, or the `.env` support, and SHALL NOT change the shape of the Settings class beyond adding
  the Timezone_Setting field (FR-CFG-4).
- THE configuration SHALL continue to be loaded exactly once, in the CLI composition root, and passed
  explicitly to components; this slice SHALL NOT introduce a module-level global config object and
  SHALL NOT mutate configuration after startup.

#### FR-CFG-2 — Precedence: CLI arguments over environment variables over `config.yaml`
*Traces to `docs/brief-config-file.md` guardrails, the existing `--adapter` override in `cli.py`, and
`security-privacy.md`.*

- THE precedence order, highest to lowest, SHALL be: **CLI_Args**, then the **Env_Source** (including
  `.env`), then the **Yaml_Source**, then the Settings field defaults. Each higher source SHALL
  override any lower source on a per-key basis.
- WHEN the same key is supplied by both the Env_Source and the Yaml_Source, THE Pipeline SHALL use the
  Env_Source value; environment variables (and `.env`) SHALL take precedence over `config.yaml`.
- WHEN a key is supplied by a CLI argument, THE Pipeline SHALL use the CLI argument value regardless of
  what the Env_Source, the Yaml_Source, or the defaults provide for that key; this SHALL generalize the
  existing pattern by which `--adapter` overrides the configured adapter value.
- THE precedence SHALL be applied per key: a CLI argument or environment variable that sets one key
  SHALL NOT suppress values that a lower source legitimately provides for other keys.
- THE precedence order SHALL be documented so users can predict which source wins for any key.

#### FR-CFG-3 — Unknown-key rejection preserved across all sources
*Traces to `docs/brief-config-file.md` guardrails and `tech.md` (`extra = "forbid"`).*

- THE Settings SHALL retain `extra = "forbid"` semantics: an unknown key SHALL be rejected at startup
  regardless of whether it originates from the Env_Source or the Yaml_Source. (CLI_Args are a fixed,
  known set defined by the argument parser and cannot introduce an unknown Settings key.)
- IF `config.yaml` contains a key that does not correspond to a known Settings field, THEN THE Pipeline
  SHALL fail at startup with a clear error naming the offending key, consistent with how an unknown
  `VOF_*` variable is rejected today.
- IF `config.yaml` is present but is not valid YAML or does not parse to a mapping of keys to values,
  THEN THE Pipeline SHALL fail at startup with a clear error identifying the file, and SHALL NOT fall
  back silently to defaults.

#### FR-CFG-4 — Timezone setting for device timestamps
*Traces to `docs/brief-config-file.md` (timezone trigger), the blood-pressure/temperature/weight
timestamp convention, and product NFR-4.*

- THE Settings SHALL define a `timezone` setting whose default value is `local`, preserving the current
  Local_Time_Default when no override is supplied.
- WHERE `timezone` is `local`, THE Pipeline SHALL interpret a device's zoneless timestamp as host local
  time and return it timezone-aware, identical to the delivered blood-pressure, temperature, and weight
  behavior.
- WHERE `timezone` is set to an explicit zone (e.g. `UTC` or an IANA zone name such as
  `America/Phoenix`), THE Pipeline SHALL interpret a device's zoneless timestamp as being in that zone
  and return it timezone-aware in that zone.
- IF `timezone` is set to a value that is neither `local` nor a resolvable zone, THEN THE Pipeline SHALL
  fail at startup with a clear error naming the invalid value, rather than silently defaulting.
- THE Timezone_Setting SHALL be consumed only at the device-timestamp decode call site (the code path
  that invokes Decode_Timestamp); it SHALL NOT change the behavior of readings that carry no device
  timestamp, whose Effective_Time remains the timezone-aware processing time.
- THE Timezone_Setting SHALL be settable from either the Env_Source (`VOF_TIMEZONE`) or the
  Yaml_Source, following the same precedence as every other key (FR-CFG-2).

#### FR-CFG-5 — Committed example, no committed secrets
*Traces to `docs/brief-config-file.md` guardrails and `security-privacy.md` (secret handling).*

- THE repository SHALL include a committed `config.yaml.example` that lists every setting expressible
  in YAML with an explanatory comment, mirroring the role `.env.example` plays for environment
  variables.
- THE `config.yaml.example` SHALL NOT contain the Secret (`VOF_API_TOKEN`) or any placeholder that
  implies the token belongs in YAML; the token SHALL remain env/`.env`-only.
- WHERE a `config.yaml` is used at runtime, THE documentation SHALL instruct users not to place the
  Secret in it and not to commit a populated `config.yaml`; the repository SHALL ignore a populated
  runtime `config.yaml` from version control, consistent with how a populated `.env` is treated.
- THE `.env.example` SHALL be updated to add the new `VOF_TIMEZONE` variable with a comment describing
  its `local` default and the override behavior.

#### FR-CFG-6 — Configuration path resolution
*Traces to `tech.md` (config loaded in `cli.py`) and `docs/brief-config-file.md`.*

- THE CLI SHALL default the Config_Path to `config.yaml` at the repository root (the process working
  directory), the same base from which `.env` is resolved.
- THE CLI SHALL accept a `--config PATH` argument that overrides the Config_Path; the file location is
  a command-line concern only (no new environment variable is introduced for it).
- WHERE `--config PATH` is provided and the file does not exist, THE CLI SHALL fail at startup with a
  clear error naming the missing path, distinguishing an explicitly requested-but-missing file from the
  ordinary absent-default case (FR-CFG-1), which remains a silent no-op.
- THE Config_Path resolution SHALL live in the composition root; no other module SHALL read
  `config.yaml` directly.

### Non-functional requirements

#### NFR-CFG-1 — No breaking changes to the object model or public surface
*Traces to product NFR-6 and the object-model conventions.*

- THIS slice SHALL introduce no change to any existing ABC method signature, any `__all__` public
  name, or any package's dependency direction; its changes SHALL be confined to `config.py`, the CLI
  composition root, the single timestamp-decode consumption path, and documentation/example files.
- Adding the Yaml_Source and the Timezone_Setting SHALL be additive; any change that would alter an
  existing public name or default-behavior contract SHALL be treated as breaking and recorded in
  `CHANGELOG.md` with a `**Breaking:**` note. The intent of this slice is to avoid such changes: with
  no `config.yaml` and no `VOF_TIMEZONE`, behavior SHALL be identical to the pre-slice state.

#### NFR-CFG-2 — Dependency directions preserved
*Traces to product NFR-6 and the structure steering doc.*

- After this slice, `uv run pytest tests/test_dependency_directions.py` SHALL pass, confirming no
  forbidden cross-package import was introduced.
- THE Yaml_Source wiring SHALL not cause any package other than the composition root to import the
  YAML-reading machinery; `config.py` SHALL remain free of business-logic imports.

#### NFR-CFG-3 — Secret and logging discipline unchanged
*Traces to product NFR-5 and `security-privacy.md`.*

- THE Pipeline SHALL NOT log configuration values at any level, including at `DEBUG`, because they may
  carry the Secret — unchanged from the current rule. This slice SHALL add no new logging of
  configuration.
- THE Secret SHALL never appear in the committed `config.yaml.example` or in any log message at any
  level — unchanged from the current rules.
- Per the user's "no secret guardrails, fail loud" decision, this slice SHALL NOT add token-specific
  code: no YAML-only ban on the Secret, no scrubbing or redaction of error text, and no catch-and-soften
  of configuration errors. Configuration failures (missing `--config` path, unknown key, malformed
  YAML, invalid `timezone`) SHALL propagate and abort startup with their underlying messages. A
  pydantic validation error MAY name the value of the specific field that failed; where that field is
  the Secret itself (e.g. a token-typed failure) this is an accepted, intended loud startup failure,
  not a leak, and errors for other keys name only that key/path/value because the configuration is
  never dumped wholesale.
- Introducing the Yaml_Source SHALL NOT create any new on-disk persistence of measurement data or any
  non-FHIR side channel; it configures the Pipeline only.

#### NFR-CFG-4 — Provenance and licensing
*Traces to the security/provenance steering doc and product license rules.*

- Every source file added or modified by this slice SHALL carry `# SPDX-License-Identifier:
  AGPL-3.0-or-later`.
- WHERE any third-party or EviTrace-ported material is included, THE slice SHALL record it in `NOTICE`
  with the required fields. No code SHALL be copied, translated, or closely paraphrased from other
  projects.

#### NFR-CFG-5 — Test coverage
*Traces to product NFR-6 and the testing steering doc.*

- THE fast test suite SHALL cover, without hardware: startup with the config file absent (identical to
  the CLI-args + env-only behavior); a `config.yaml` supplying values that a Settings field then
  reflects; env precedence winning over a conflicting `config.yaml` value (FR-CFG-2); a CLI argument
  winning over conflicting env and `config.yaml` values for the same key (FR-CFG-2); `--config PATH`
  selecting a non-default file (and the default `config.yaml` not being read in that case); `--config`
  to a non-existent path failing loudly at startup with the path named (FR-CFG-6); an unknown YAML key
  being rejected at startup (FR-CFG-3); an invalid/unparseable `config.yaml` being rejected (FR-CFG-3);
  the `timezone` default (`local`) reproducing the existing host-local decode; an explicit `timezone`
  (e.g. `UTC`) changing the decoded zone; and an invalid `timezone` value being rejected (FR-CFG-4).
- THE existing heart-rate, blood-pressure, oxygen-saturation, body-temperature, and body-weight suites
  (including the dependency-direction test) SHALL remain green as the regression guardrail, confirming
  the vital-sign path is unchanged.

#### NFR-CFG-6 — Documentation and traceability
*Traces to product NFR-6, `changelog-rules.md`, `docs/brief-config-file.md`, and
`docs/brief-validation-modes.md` (independent affirmation of the structural driver).*

- THE `CHANGELOG.md` SHALL gain an entry recording the new `config.yaml` configuration source
  (permanent layer, file optional), the CLI-args → env → `config.yaml` → defaults precedence order,
  the `VOF_TIMEZONE` / `timezone` key, and the `config.yaml.example`.
- THE `docs/brief-config-file.md` SHALL be updated to record that the brief has been promoted to
  `spec/config-file` as the final phase-2 slice, capturing that the decision was driven by the
  timezone trigger plus the structural driver — the latter **independently affirmed** in
  `docs/brief-validation-modes.md` — and **not** by flat-list length, which the phase-2 assessment
  closed as "not awkward".
- THE documentation SHALL keep both drivers (length and structure) visible, and SHALL cite
  `docs/brief-validation-modes.md` as independent corroboration that flat `VOF_<VITAL>_<BOUND>` pairs
  are the wrong *shape* for planned work, so a future reader understands the config layer landed on
  structure and the timezone key — not despite the length assessment, but orthogonally to it.

---

## Out of scope

Per the product steering document, ADR-0001, and the guardrails in `docs/brief-config-file.md`, this
spec excludes:

- **Per-vital validation modes** — keyword modes, ±k·SD flagging bands with a selectable k, and
  explicit per-person bounds sketched in `docs/brief-validation-modes.md`. That brief is the
  independent affirmation that motivates the structural driver above, but it is *not* implemented here:
  this slice adds only the nested config *mechanism* those modes would eventually ride on, and builds
  none of the mode logic (no keyword modes, no k-factor band, no per-person bounds, no flagging via
  FHIR `interpretation`). Those modes remain idea-only and would be their own spec, with their own
  requirements and a `CHANGELOG.md` entry.
- **Restructuring the flat `VOF_<VITAL>_<BOUND>` Range_Keys into nested YAML groups.** The range keys
  stay flat and env-authoritative; `config.yaml` may mirror them under the existing flat names but this
  slice does not introduce a nested per-vital range schema.
- **Making YAML authoritative over environment variables.** Env (and `.env`) stay on top; YAML is a
  lower-precedence convenience layer only.
- **Code that enforces "no secret in a config file."** The docs recommend keeping the Secret in
  `.env`/env and the committed example omits it, but per the "no secret guardrails" decision this slice
  builds **no** code that rejects, scrubs, or special-cases the token in YAML. Keeping the token out of
  a committed config file is a documentary/operational convention (`.gitignore` + example), not a
  runtime check.
- **Any new configuration format beyond a single `config.yaml` file** (no TOML, JSON, INI, or
  remote/hierarchical config services).
- **Multiple simultaneous devices, persistence beyond in-memory storage, remote/cloud deployment,
  SMART on FHIR, and outbound FHIR sinks** — all remain phase-4-or-later and are neither built nor
  referenced as supported here.
- **Any new vital sign, adapter, parser, or FHIR mapper.** This slice changes configuration only.
