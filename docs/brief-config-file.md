<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Brief — a `config.yaml` if configuration keeps growing

**Status:** Idea only. Not scheduled, not a decision. Recorded so it need not be re-derived.
**Not part of** the `home-health-devices` spec. Do not act on this while that spec is in flight.

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
