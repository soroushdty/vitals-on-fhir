<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Brief — a `config.yaml` if configuration keeps growing

**Status:** **Promoted.** This brief has been folded in as the final phase-2 slice and is now
implemented as `spec/config-file` (`.kiro/specs/config-file/`). It began idea-only; the rest of this
document is preserved as the historical record of how the decision was reached. See the
**Promotion** section at the end for what actually opened the spec and what it does and does not build.
**Originally not part of** the `home-health-devices` spec (that gate is long cleared, per the
checkpoints below).

## The idea

Today all configuration is environment variables via `pydantic-settings` (`VOF_*` prefix, loaded
once in `cli.py`, `.env` supported, `extra="forbid"`). As phase 2 adds more vital types, the
`VOF_*` surface grows (e.g. `VOF_BP_SYSTOLIC_MIN/MAX`, `VOF_BP_DIASTOLIC_MIN/MAX`, and the future
`VOF_SPO2_*`, `VOF_TEMP_*`, `VOF_WEIGHT_*`). If that surface gets large enough that a flat env list
is awkward, consider supporting an optional `config.yaml` as an **additional** source layered under
`pydantic-settings`, with env vars still taking precedence.

## Why it might be worth it later

- Grouping related keys (per-vital plausible ranges) reads better nested than as a flat prefix list.
- A single checked-in-example file is easier to document than a long `.env.example`.
- `pydantic-settings` already supports custom settings sources, so YAML can be added without
  abandoning the current model or the `VOF_*` env vars.

## Timezone key (the trigger for this brief)

The blood-pressure parser interprets the device's zoneless timestamp as **host local time**
(see `.kiro/specs/home-health-devices/design.md`). That choice is currently implicit. If a config
file lands, add a `timezone` key with **`local` as the default**, allowing an explicit override
(e.g. `UTC`, or a named zone) for users whose device and host differ. Until then, local-time-implicit
is the documented behavior and no config key exists.

## Promotion checkpoint (when to revisit)

The original "do not act while `home-health-devices` is in flight" gate is cleared: that spec is
delivered. But its substantive trigger — a flat `VOF_*` env list becoming *awkward* — is **not yet
met**. Blood pressure added only four keys (`VOF_BP_SYSTOLIC_MIN/MAX`, `VOF_BP_DIASTOLIC_MIN/MAX`),
bringing the surface to roughly a dozen variables, which a flat list still handles fine.

Promotion is therefore gated on the **remaining phase-2 vitals**, not on `home-health-devices`. Each
sibling spec (oxygen saturation, body temperature, body weight) adds its own `VOF_*` range keys. The
next sibling spec should include an explicit checkpoint: after that vital lands, list the projected
total `VOF_*` surface and decide whether it has crossed "awkward". Promote this brief to its own spec
at the point that judgment turns yes — with concrete keys in front of you, not a forecast. Because
config is loaded once in `cli.py` and passed explicitly, adding YAML later is a change to the
composition root only; there is no scattered call-site migration, so backfilling stays cheap.

### Checkpoint — after oxygen saturation (`spec/oxygen-saturation`)

Oxygen saturation is the first sibling spec to land after this brief was written, so it carries the
explicit checkpoint the section above asked for. It added two flat keys, `VOF_SPO2_MIN` and
`VOF_SPO2_MAX`, bringing the counted `VOF_*` surface (in `.env.example` and `config.py`) to **15**:

- 5 non-range keys: `VOF_API_TOKEN`, `VOF_HOST`, `VOF_PORT`, `VOF_ADAPTER`, `VOF_DEVICE_NAME`
- 2 storage/identity keys: `VOF_PATIENT_ID`, `VOF_STORE_MAX`
- 8 per-vital plausibility-range keys: `VOF_HR_MIN/MAX` (2), `VOF_BP_SYSTOLIC_MIN/MAX` +
  `VOF_BP_DIASTOLIC_MIN/MAX` (4), `VOF_SPO2_MIN/MAX` (2)

**Judgment: not yet awkward.** Fifteen flat variables — of which the eight range keys already follow a
clear `VOF_<VITAL>_<BOUND>` convention — are still comfortable as an env list and a commented
`.env.example`. The nesting benefit is real but not yet worth a second config source. The two
remaining phase-2 vitals will each add a small number of range keys (`VOF_TEMP_*`, `VOF_WEIGHT_*`),
which would push the surface toward the high teens. That is the point to re-run this checkpoint: if
body temperature and body weight both land and the range-key group crosses roughly a dozen entries on
its own, revisit whether nested per-vital range config earns its own spec. For now the flat list
holds; no promotion.

### Checkpoint — after body temperature (`spec/body-temperature`)

Body temperature is the second sibling spec to land after this brief was written, so it re-runs the
checkpoint above. It added two flat keys, `VOF_TEMP_MIN` and `VOF_TEMP_MAX`, bringing the counted
`VOF_*` surface (in `.env.example` and `config.py`) to **17**:

- 5 non-range keys: `VOF_API_TOKEN`, `VOF_HOST`, `VOF_PORT`, `VOF_ADAPTER`, `VOF_DEVICE_NAME`
- 2 storage/identity keys: `VOF_PATIENT_ID`, `VOF_STORE_MAX`
- 10 per-vital plausibility-range keys: `VOF_HR_MIN/MAX` (2), `VOF_BP_SYSTOLIC_MIN/MAX` +
  `VOF_BP_DIASTOLIC_MIN/MAX` (4), `VOF_SPO2_MIN/MAX` (2), `VOF_TEMP_MIN/MAX` (2)

**Judgment: still not yet awkward — but close.** Seventeen flat variables, of which the ten range keys
follow the clear `VOF_<VITAL>_<BOUND>` convention, remain workable as an env list and a commented
`.env.example`. The nesting benefit keeps growing, but the flat list still reads and documents fine;
promoting a second config source purely on length is not yet warranted. Only one phase-2 vital remains
(`VOF_WEIGHT_*`), which would add a small number of range keys and push the surface toward the high
teens / low twenties. That is the point to re-run this checkpoint one last time for phase 2: if body
weight lands and the range-key group is clearly unwieldy as a flat list, revisit whether nested
per-vital range config earns its own spec. For now the flat list holds; no promotion on length.

(This checkpoint records the count and judgment only. It builds no config layer, consistent with the
brief's guardrails.)

### Checkpoint — after body weight (`spec/weight-body-mass`)

Body weight is the **final** phase-2 vital, so this checkpoint closes the phase-2 length-driver
assessment. It added two flat keys, `VOF_WEIGHT_MIN` and `VOF_WEIGHT_MAX`, bringing the counted
`VOF_*` surface (in `.env.example` and `config.py`) to **19**:

- 5 non-range keys: `VOF_API_TOKEN`, `VOF_HOST`, `VOF_PORT`, `VOF_ADAPTER`, `VOF_DEVICE_NAME`
- 2 storage/identity keys: `VOF_PATIENT_ID`, `VOF_STORE_MAX`
- 12 per-vital plausibility-range keys: `VOF_HR_MIN/MAX` (2), `VOF_BP_SYSTOLIC_MIN/MAX` +
  `VOF_BP_DIASTOLIC_MIN/MAX` (4), `VOF_SPO2_MIN/MAX` (2), `VOF_TEMP_MIN/MAX` (2),
  `VOF_WEIGHT_MIN/MAX` (2)

**Judgment: not promoted on length.** Nineteen flat variables, of which the twelve range keys follow
the clear `VOF_<VITAL>_<BOUND>` convention, remain workable as an env list and a commented
`.env.example`. The nesting benefit is real and has grown across the four phase-2 slices, but a flat
list of this size still reads and documents fine, and every range key maps cleanly to a single
`(min, max)` pair — the shape a flat prefix list handles well. Promoting a second config source purely
on the length reached at the end of phase 2 is not warranted.

**Phase-2 length-driver assessment — closed.** With all four phase-2 vitals landed (blood pressure,
oxygen saturation, body temperature, body weight), the flat env-var list never crossed "awkward" on
length alone. The recommendation is therefore to **leave the `config.yaml` idea idea-only** for now:
do not open a config-file spec on the strength of the length driver. If `config.yaml` is ever pursued,
the more likely trigger is the **structural driver** below (per-vital validation modes), not list
length — future work (e.g. a fifth vital in a later phase, or a `timezone` key) should re-weigh both
drivers together at that point.

(This checkpoint records the count and judgment only. It builds no config layer, consistent with the
brief's guardrails.)

## A second, structural driver — per-vital validation modes

Everything above weighs the *length* of the flat env list as the trigger for `config.yaml`. A second,
**structural** driver is now on the horizon and is worth recording separately: per-vital **validation
modes**, sketched in `docs/brief-validation-modes.md` (also idea-only). Those modes — predefined
keyword modes, a ±k·SD flagging band with a selectable k, and explicit per-person bounds — do **not**
express cleanly as flat `VOF_<VITAL>_<BOUND>` pairs. Keyword modes, k-factors, and per-person option
sets are structured/nested by nature, so a flat prefix list is the wrong shape for them regardless of
how many entries it has.

This does **not** change the current "not yet awkward" judgment on length. It adds a distinct
consideration: if per-vital validation modes are ever pursued, their structured shape — not the flat
list's length — could be the thing that tips the balance toward a nested `config.yaml`. Record both
drivers when this brief is eventually promoted so the decision weighs length and structure separately.

## Guardrails if this is ever picked up

- Keep env vars authoritative; YAML is a lower-precedence convenience layer, not a replacement.
- Preserve `extra = "forbid"` semantics (reject unknown keys) in whatever source is added.
- Config stays loaded once in `cli.py` and passed explicitly; no module-level global, no mutation
  after startup (per `tech.md`).
- Never put secrets (`VOF_API_TOKEN`) in a committed config file; secrets stay in `.env`/env only.
- This would be its own small spec with its own requirements and a `CHANGELOG.md` entry.

## Promotion — folded in as the final phase-2 slice (`spec/config-file`)

This brief is now promoted to its own spec, `spec/config-file` (requirements in
`.kiro/specs/config-file/requirements.md`), delivered as the last slice of phase 2 after the four
vital-sign siblings (blood pressure, oxygen saturation, body temperature, body weight).

**What actually opened it — not list length.** The phase-2 length-driver assessment above closed with
"not promoted on length": nineteen flat `VOF_*` variables, twelve of them clean
`VOF_<VITAL>_<BOUND>` range pairs, still read and document fine as an env list. That judgment stands.
The spec was opened on the **other two drivers this brief recorded**:

- **The timezone trigger.** The device-timestamp-as-host-local-time choice is currently implicit. The
  spec makes it an explicit `timezone` key (**default `local`**, overridable to `UTC` or a named
  zone), which is exactly the concrete key this brief named as the trigger for a config file. This is
  the one behavioral change the config layer carries.
- **The structural driver — independently affirmed.** Per-vital validation modes
  (`docs/brief-validation-modes.md`) do not express as flat `VOF_<VITAL>_<BOUND>` pairs. This is not
  the config brief arguing for itself: `brief-validation-modes.md` was written during the separate
  `body-temperature` slice, for the separate purpose of deciding how personal/clinical thresholds
  should work, and it independently concluded that those modes "ride on structured configuration"
  because "modes, k-factors, and per-person option sets do not express cleanly as flat
  `VOF_<VITAL>_<BOUND>` env pairs." Two separate work streams reaching "flat env pairs are the wrong
  *shape*" is the affirmation that settles the driver. The spec builds the nested-config **mechanism**
  those modes would ride on, but builds **none** of that logic — validation modes remain idea-only and
  stay their own future spec.

**Two clarifications the spec sharpens from the original idea:**

- **The layer is not optional; only the file is.** The brief above calls this an *optional*
  `config.yaml`. Once implemented, the `config.yaml` layer is a permanent tier of the precedence chain.
  What is optional is whether a `config.yaml` file exists on disk — absent, it contributes nothing,
  exactly like a missing `.env`.
- **Full authority order: CLI args → env (and `.env`) → `config.yaml` → defaults.** The brief framed
  precedence as "env vars over YAML," which is correct but incomplete: command-line arguments outrank
  env vars, generalizing the existing `--adapter` override. So a CLI arg beats an env var beats
  `config.yaml` beats a built-in default, per key.
- **The file location is command-line-selectable via `--config PATH`.** The spec defaults the config
  path to `config.yaml` at the repository root (the working directory `.env` is already resolved from)
  and accepts a `--config PATH` flag that overrides *which* file the `config.yaml` tier reads. `--config`
  selects the file location; it is not a per-key value override. An explicitly supplied `--config` path
  that does not exist **fails loudly** at startup with the path named, whereas a missing *default* file
  stays a silent no-op (the ordinary absent case). No new environment variable is added for the path.
- **No secret guardrails in code; configuration errors fail loud.** Per the user decision the spec
  folds in, there is **no** token-specific code — no YAML-only ban on `VOF_API_TOKEN`, no scrubbing or
  redaction of error text, and no catch-and-soften. Configuration failures (missing `--config` path,
  unknown key, malformed YAML, invalid `timezone`) propagate and abort startup with their underlying
  messages. Keeping the secret out of a committed config file stays a documentary/operational
  convention (`.gitignore` + the token-omitting `config.yaml.example`), not a runtime check; the only
  secret protection is the pre-existing "never log configuration values" rule, which this slice does
  not weaken.

**Guardrails carried into the spec unchanged (from "Guardrails if this is ever picked up" above):**

- Env vars (and `.env`) stay authoritative over `config.yaml`; CLI args stay authoritative over both;
  `config.yaml` is a strictly lower-precedence layer than env, above only the defaults.
- `extra = "forbid"` is preserved across both sources — unknown keys are rejected regardless of origin.
- Config stays loaded once in `cli.py` and passed explicitly; no module-level global, no mutation
  after startup.
- The secret (`VOF_API_TOKEN`) never enters any committed config file; it stays env/`.env`-only.
- A committed `config.yaml.example` documents the YAML surface, mirroring `.env.example`.

**Both drivers recorded together, as this brief asked — and they answer different questions.** The
phase-2 assessment asked whether the flat list is too *long* and answered no; that judgment stands.
The structural driver asks whether the flat list is the wrong *shape* for planned work, and
`brief-validation-modes.md` affirms — from a separate slice — that it is. So "not awkward on length"
and "the config layer is justified" are not in tension: they address length and structure separately.
Length did not tip the balance; the timezone key plus the independently-affirmed structural driver
did. Future work (a fifth vital in a later phase, or the validation-modes spec) should re-weigh length
and structure together on top of the mechanism this slice now provides.
