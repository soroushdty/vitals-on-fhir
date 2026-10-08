# Changelog

All significant changes to vitals-on-fhir are recorded here.
This file is permanent and is never truncated or rewritten. See `changelog-rules.md` for the entry format and policy.

---

## [2026-10-08] — Docs describe the current scope

The README, architecture guide and roadmap still described a heart-rate-only
MVP, although blood pressure, SpO2, temperature and weight have shipped. An
outside reader who saw only the README concluded the project was heart rate
only (#40).

- Changed: README opens with a table of the five vital signs (Bluetooth
  service, adapters, LOINC, UCUM, US Core profile) and states what is tested
  on hardware and how conformance was last checked; the configuration table
  lists `VOF_TIMEZONE` and every plausibility bound
- Changed: `docs/architecture.md` lists the shipped vital signs, adapters,
  parsers, validators and `MapperRegistry`, with a `ComponentVital` example
- Changed: `docs/roadmap.md` marks phase 1 delivered and phase 2's four vital
  signs shipped (the phase stays open per ADR-0001)
- Changed: `docs/README.md` points to the requirements in
  `.kiro/steering/product.md` instead of a nonexistent SRS, notes ADR-0003 as
  reserved, and lists the briefs and all five protocol citations
- Changed: steering `object-model.md` and `structure.md`, and the
  `fhir/mappers.py` docstring, no longer call `ComponentVitalMapper` a stub

## [2026-10-08] — FHIR search semantics, injected mapper registry

Fixes from an outside review of the repository: the FHIR search API now follows
FHIR token and date search, the orchestrator uses the mappers it is given, and
the dependency-direction test enforces the rule about `cli` it documented.

- Fixed: `GET /fhir/Observation?date=` with a value without a UTC offset
  raised `TypeError` (a 500). Such a value is now in the zone set by
  `search_timezone` (#36)
- Added: config `search_timezone` (`VOF_SEARCH_TIMEZONE`): `UTC` (default),
  `local` (the host's zone, as FHIR suggests), or an IANA name. Days are
  midnight to midnight by that zone's wall clock, across daylight-saving
  changes. `create_app` takes it as `search_timezone`
- Changed: a `date` value covers the range its precision implies (`2026-10-07`
  is the whole day); `eq`, `ge`, `gt`, `le`, `lt` compare that range with
  `effectiveDateTime`, and `gt` / `lt` are no longer treated as `ge` / `le`.
  Repeated `date` parameters are combined. An invalid value returns 400
  (`invalid`) instead of an unfiltered search; `ne`, `sa`, `eb`, `ap` return 400
  (`not-supported`) (#36)
- Fixed: `code=system|code` matches the system as well as the code; `|code`
  and `system|` are supported (#37)
- **Breaking:** `ObservationStore.search` takes `system` and `date_before`
  (exclusive) in place of `date_to` (inclusive)
- **Breaking:** `Orchestrator` takes `mappers: MapperRegistry` in place of the
  `mapper: VitalMapper` it stored but never used (#38)
- Added: `fhir.MapperRegistry` and `fhir.default_mapper_registry()`
- **Breaking:** removed `fhir.register_mapper` and `fhir.resolve_mapper` and the
  module-level registry; importing `vitals_on_fhir.fhir` no longer registers
  mappers as a side effect (#38)
- Changed: `tests/test_dependency_directions.py` forbids importing `cli` from
  every package and from top-level modules, and tests the rule table itself
  (#39)
- Changed: steering (`object-model.md`, `fhir-conventions.md`,
  `structure.md`), `docs/fhir-api.md`, the README, `.env.example`,
  `config.yaml.example` and the CapabilityStatement describe the search
  behaviour

## [2026-10-07] — Say why the device is not connected, on the dashboard

The service already logged why each connection attempt failed, but the dashboard
only said "Connecting to the device…". The reason now reaches the dashboard, and
the docs say what to do about each one.

- Added: `adapters.StateCallback`, the type of the `on_state_change` callback,
  now `(state, reason=None)`. `reason` says why the device is not connected yet;
  adapters may still pass the state alone. It replaces the repeated
  `Callable[[ConnectionState], Awaitable[None]]` annotations
- Changed: `BleConnection` reports the current state again with the reason after
  each failed attempt; the not-found reason suggests switching the device's
  broadcast off and on again
- Changed: the `connection_state` WebSocket envelope has an optional `reason`,
  replayed to clients that connect later; `DashboardBroadcaster.on_state_change`
  takes it
- Added: the dashboard shows the reason under the connection status until the
  device connects
- Added: a troubleshooting section in `docs/device-compatibility.md`, and a
  pointer to it in the README's Mi Band steps

## [2026-10-07] — Dashboard: light and dark themes, repository link

- Added: a Light / Dark switch at the top right of both screens. Until the user
  chooses, the page follows the system's `prefers-color-scheme`; the choice is
  stored in `localStorage` (the theme name only) and applied from `<head>` by the
  new `theme.js`, so a reload does not flash the other theme
- Added: a "GitHub ↗" link to the repository, opening in a new tab
  (`rel="noopener noreferrer"`)
- Changed: `style.css` defines a dark palette for every colour token; button
  text, the error message and the token field now use tokens instead of fixed
  colours
- Changed: the logo has a transparent background, in two variants
  (`logo-light.webp`, `logo-dark.webp`, the dark one with light lettering); the
  page and the README show the one for the active theme. `logo.jpeg` is removed
- Added: `tools/make_logo_variants.py`, which makes both variants from the
  original artwork

## [2026-10-07] — Dashboard: scrolling heart-rate chart

The "Heart rate, last 2 minutes" chart squeezed a fixed window into the card. It is
now "Heart rate": a strip at a fixed time scale with a gridline every 10 seconds,
counted from the session's first reading, that grows to the right and scrolls
sideways.

- Changed: the x axis is labelled in seconds (`0 s`, `10 s`, …) at 6 px per second;
  the bpm axis stays fixed while the plot scrolls
- Added: the chart follows the latest reading unless the user scrolls back; a
  "Latest ›" button returns to it
- Changed: a silence longer than 5 s (for example a disconnect) breaks the line
  instead of joining across the gap
- Changed: readings are kept for 30 minutes instead of 2; lowest, average and
  highest cover the readings kept

## [2026-10-07] — Dashboard: start page with the token, Home button, side-by-side layout

The access token moved from a card that stayed at the top of the page onto the
start page, next to the safety and scope notes, so the dashboard has one way in.
The FHIR resource viewer now sits beside the readings instead of below them.

- Changed: the welcome dialog is now a start page with the notes and the token
  field (hidden in demo mode); "I understand — connect" checks the token against
  `GET /fhir/metadata` and says when it is not accepted
- Added: a Home button on the app page disconnects, forgets the token and returns
  to the start page; if the server stops accepting the token (for example it
  restarted with a new one), the page returns there with that message instead of
  retrying forever
- Changed: the token is no longer kept between page loads, and the
  acknowledgement is no longer remembered for the browser session; the start page
  asks for both on each load
- Changed: on screens 960 px and wider, the FHIR resources card is a right-hand
  column beside the latest reading, chart and simulator, and stays in view while
  the left column scrolls; narrower screens keep one column
- Added: a "Demo mode: simulated data" badge in the app page header

## [2026-10-07] — Dashboard: welcome notes, device details, FHIR resource viewer

The dashboard now shows the FHIR it receives. The safety and scope warnings moved
from the bottom of the page into a notice that must be acknowledged before the page
connects, and a FHIR resource viewer took their place. The device behind the
readings is shown under the heart rate, read from the FHIR Device resource.

- Added: welcome dialog with the Bluetooth-broadcast and research-use warnings; the
  page connects only after "I understand" (remembered for the browser session),
  and a footer button reopens it
- Added: FHIR resources card: the latest Observation as highlighted JSON, values
  changed since the previous reading flashed, pause/resume, the last 20 readings,
  and `Patient/…` / `Device/…` references that open the resource from the API
- Added: device details (manufacturer, model, identifiers, simulated flag) in the
  latest-reading card, from `GET /fhir/Device/{id}`
- Changed: `create_app(device=...)` also accepts a zero-argument callable, called on
  every Device read; `cli.py` passes one, so the Device reflects what the adapter
  learns after startup (the matched band's Bluetooth address)
- Changed: `MiBand10Adapter.device_info` has no identifier until a band is matched;
  it previously published `bluetooth_address` = `"unknown"`
- Fixed: `docs/fhir-api.md` example used `Device/xiaomi-smart-band-10`; the id is
  `smart-band-10`

## [2026-10-07] — Find BLE devices reliably

A Xiaomi Smart Band 10 that was broadcasting heart rate was never found, for three
reasons: `VOF_DEVICE_NAME` had to equal the full advertised name; one empty scan
stopped acquisition for the rest of the session; and a band left connected to the
computer (paired, or kept by an earlier run) does not advertise, so no scan could
see it. The service's own `INFO` logs were dropped as well, which hid all of this.

- Changed: `VOF_DEVICE_NAME` matches any part of the advertised name, ignoring
  case (`Smart Band 10` now selects `Xiaomi Smart Band 10 9940`). A value that was
  the exact full name still works.
- Changed: `BleConnection.connect()` keeps looking with capped backoff when no
  device is found or the connection fails, logging the reason at `WARNING` (the
  devices seen and whether the name filter excluded them). It no longer raises
  for those cases; it still raises `RuntimeError` when `bleak` is unavailable.
- Added: on Linux, a matching device that is already connected to the computer is
  used when nothing matching is advertising (looked up in BlueZ over D-Bus).
- Fixed: a link whose notification subscription fails is closed again instead of
  being left open, where it kept the device from advertising.
- Fixed: `cli.main()` sends the package's `INFO` logs (connection events,
  rejected readings) to stderr.
- Added: `adapters.ble.DeviceNotFoundError`.

## [2026-10-06] — Body-temperature measurement site in bodySite

Thermometers can report where the temperature was taken, but the parser skipped
that field, and readings from different sites are not directly comparable. The
site now reaches `Observation.bodySite` as a SNOMED CT concept, and the HL7 FHIR
validator accepts every code against US Core Body Temperature (ADR-0006, issue #11).

- Added: `docs/adr-0006-temperature-measurement-site.md`
- Added: `vitals.BodySite` (SNOMED CT code and display); `VitalSign.body_site`
  (default `None`)
- Changed: `TemperatureMeasurementParser` decodes Temperature Type (GSS
  Table 3.370); "Body (general)" and reserved values give no site
- Changed: `ScalarVitalMapper` and `ComponentVitalMapper` set `bodySite` when a
  site is known
- Changed: steering `fhir-conventions.md` (when `bodySite` and similar device
  context may be added) and `object-model.md`;
  `docs/protocol-body-temperature-measurement.md` (site table, codes, and the static
  Temperature Type characteristic, which is not read yet)

## [2026-10-06] — Honour device-reported measurement status

Blood-pressure cuffs and pulse oximeters report whether a reading is trustworthy,
but those status bits were ignored, so readings the device called invalid were
published as `final`. Untrustworthy or not-final readings are now rejected;
irregular pulse is accepted. The choices are in ADR-0005 (issue #7).

- Added: `docs/adr-0005-honour-device-reported-measurement-status.md`
- Added: `vitals.DeviceIssue`; `VitalSign.device_issues` (default empty)
- Added: `validation.DeviceStatusValidator`, in the default validator chain
- Changed: `BloodPressureMeasurementParser` decodes Measurement Status (GSS
  Table 3.55); `PlxContinuousMeasurementParser` decodes Measurement Status and
  Device and Sensor Status (PLXS 1.0.1 Tables 3.4 and 3.5)
- Changed: both protocol docs list every status bit and its handling; the PLX doc
  now cites PLXS rather than the GSS for these fields; steering `object-model.md`

## [2026-10-06] — Record only the configured user on shared devices

Multi-user blood-pressure cuffs and weight scales tag each reading with a user ID,
which was ignored, so one person's readings could be filed under another's Patient.
The parsers now compare that ID with a configured user and reject the rest, without
ever keeping the ID. The decision and the reject-by-default choice are in ADR-0004
(issue #8).

- Added: `docs/adr-0004-attribute-multi-user-device-readings.md`
- Added: `VOF_DEVICE_USER_ID` (`Settings.device_user_id`, 0–254, default unset)
- Added: `vitals.DeviceUserMatch`; `BloodPressure.device_user` and
  `BodyWeight.device_user` (default `None`)
- Added: `validation.DeviceUserValidator`, in the default validator chain
- Changed: `BloodPressureMeasurementParser`, `WeightMeasurementParser`,
  `BloodPressureBleAdapter` and `WeightScaleBleAdapter` take `device_user_id`
- Changed: steering `security-privacy.md` (the user ID is never logged; no raw
  payload bytes for BP or weight) and `object-model.md`; protocol docs, README,
  `.env.example`, `config.yaml.example`
- **Breaking:** a multi-user cuff or scale records nothing until
  `VOF_DEVICE_USER_ID` is set. Single-user devices and the mock adapters are
  unaffected

## [2026-10-06] — SpO2 Observations carry LOINC 2708-6

US Core Pulse Oximetry and the base FHIR `oxygensat` profile require LOINC 2708-6 next to
59408-5, so every SpO2 Observation failed validation. Both codes are now emitted, and the HL7
FHIR validator reports no errors (issue #17).

- Added: `VitalSign.additional_loinc_codes` (default `()`); `OxygenSaturation` sets `("2708-6",)`
- Changed: `ScalarVitalMapper` and `ComponentVitalMapper` emit `loinc_code` first, then one
  LOINC coding per additional code
- Changed: `InMemoryObservationStore.search(code=...)` matches any coding, not only the first,
  so `GET /fhir/Observation?code=2708-6` finds SpO2 readings
- Changed: steering `fhir-conventions.md` ("Choosing codes": a profile may require more than one
  code) and `object-model.md`; `docs/brief-standards-alignment.md`, `docs/fhir-api.md`

## [2026-10-05] — Mark patient-generated and simulated Observations

Observations now say that the patient collected them with a personal health device, so a
receiving EHR can tell them apart from clinician-recorded vitals, and simulated readings are
labelled as test data. The choices, sources and validator evidence are in ADR-0002 (issue #6).

- Added: `docs/adr-0002-mark-patient-generated-and-simulated-observations.md`
- Changed: `ScalarVitalMapper` and `ComponentVitalMapper` set `performer` to the Patient and
  add the PHD IG category `PhdObservationCategories#phd` after `vital-signs`
- Added: `DeviceInfo.simulated` (default `False`); the five mock adapters set it. `build_device`
  labels a simulated Device with the `HTEST` security label (`v3-ActReason`)
- Added: `fhir.mark_simulated` (and `__all__`), `fhir/provenance.py` (`PHD_CATEGORY`,
  `HTEST_SECURITY_LABEL`); the `Orchestrator` labels every Observation from a simulated device
- Changed: steering `fhir-conventions.md` (canonical Observation shape, and when fields beyond
  US Core requirements are allowed) and `object-model.md`; `docs/fhir-api.md`,
  `docs/standards-and-related-work.md`, and the open question in `brief-standards-alignment.md`
- Migration: a third-party adapter for simulated data should set `DeviceInfo(simulated=True)`.
  A third-party `VitalMapper` should add `performer` and the `phd` category as well

## [2026-10-05] — Demo mode: run the mock without a token

`VOF_API_TOKEN` is now optional. Without it the service starts in demo mode: a mock adapter
runs with authentication off, so a first run needs no setup. A real device still requires a
token, and asking for one without a token stops at startup instead of falling back to
simulated data.

- Added: `demo_mode` setting (`VOF_DEMO_MODE`, `demo_mode:` in `config.yaml`, CLI
  `--demo` / `--no-demo`), default on. Off makes a missing token a startup error
- Added: `AnonymousAuthenticator` in `api` (and `__all__`), and
  `Authenticator.requires_credentials` (default `True`); with `False` the FHIR routes,
  `/mock/*` and `/ws` skip the token check
- Added: public `GET /status` returning `{"auth_required": bool}`; the dashboard hides its token
  form and connects straight away when it is `false`, showing a "Demo mode" note
- Added: startup warnings in demo mode, and a second one when `VOF_HOST` is not loopback
- Changed: `Settings.api_token` is `str | None` (default `None`). An empty `VOF_API_TOKEN=`
  counts as unset, and so does an empty `VOF_DEVICE_NAME=` (it previously filtered for a
  device named `""`, so a copied `.env.example` never connected to a real device)
- Changed: `.env.example` comments out `VOF_API_TOKEN` and adds `VOF_DEMO_MODE`, so an
  unedited copy gives the built-in defaults; `tests/test_config.py` checks that, and that it
  lists every setting
- Changed: steering `product.md` (FR-12, NFR-5), `security-privacy.md`, `tech.md`,
  `object-model.md`, `structure.md`, `testing.md` describe the demo-mode exception
- Migration: a `.env` with `VOF_API_TOKEN` set behaves as before. Real-device setups that
  never set a token already failed to start and still do, now with a clearer message

## [2026-10-05] — Mock heart-rhythm scenarios and live chart

The `mock` adapter now simulates named heart rhythms that you pick in a dropdown and start with a
Simulate button on the dashboard (each starts from the beginning and clears the previous run). The
dashboard also shows a live chart and a correct connection status for clients that connect after
the device.

- Added: `adapters/builtin/hr_scenarios.py` — `HeartRateScenario` (steady: `NORMAL_SINUS_RHYTHM`,
  `SINUS_BRADYCARDIA`, `SINUS_TACHYCARDIA`, `ATRIAL_FIBRILLATION`; episodes: `PAROXYSMAL_AF`, `SVT`,
  `ATRIAL_FLUTTER`; other: `EXERCISE_RAMP`, `OFF_WRIST`, `DISCONNECT_RECONNECT`) and
  `ScenarioEngine`. Regular rhythms are a mean-reverting walk; AF draws
  each reading independently; episodes start normal and change abruptly; exercise loops a ramp
- Added: `MockAdapter` takes `scenario`, `rng` and `on_state_change`, has a settable `scenario`
  property, and `HeartRateScenarioControl` exposes the options. Off-wrist readings carry
  `sensor_contact=False` (the validator rejects them); a dropout reports `RECONNECTING` then
  `CONNECTED` and yields nothing in between. Without a `scenario` it still emits a fixed 72 bpm, so
  existing tests and callers are unaffected
- Added: starting a scenario clears the previous run: `MockAdapter` takes `on_restart` (awaited
  between the last old reading and the first new one, so no stale reading can follow it) and its
  wait between readings is cut short; `cli.py` wires it to the new `InMemoryObservationStore.clear()`
  and `DashboardBroadcaster.reset()`, which sends a `{"type": "reset"}` envelope that every open
  dashboard answers by clearing its chart and readings
- Added: token-protected `GET /mock/scenarios` (id, label, description, group) and
  `PUT /mock/scenario` (`api/mock_control.py`; starts the scenario from the beginning, or restarts
  it if it is already running), registered only when `create_app(scenario_control=...)` is given, i.e. only with `--adapter mock`
- Added: `VOF_MOCK_INTERVAL` (default `1.0` s) config variable; started from the CLI, the `mock`
  adapter now emits one reading per second (was one per 10 ms)
- Added: dashboard "Simulate a heart rhythm" panel (shown only for the mock adapter), a live
  two-minute heart-rate chart with lowest/average/highest, and a "no new valid reading" notice
  when the device is connected but silent for 8 seconds, all in `dashboard/static`
- Changed: `DashboardBroadcaster.register` sends the last known `connection_state` to a newly
  connected client, and the dashboard marks the device connected when a reading arrives
- Changed: dashboard static files are served with `Cache-Control: no-cache` so an upgraded
  dashboard is not hidden behind a browser's heuristically cached copy

## [2026-09-23] — config.yaml configuration layer (spec/config-file)

Implements the fifth and final phase-2 slice: promotes the idea-only
`docs/brief-config-file.md` into a working feature. It adds a permanent
`config.yaml` configuration tier beneath command-line arguments and environment
variables, plus a single behavioral key — `timezone` — that makes the
device-timestamp interpretation explicit and overridable. It adds no vital sign,
adapter, FHIR mapper, validator, store, sink, or API route; the change is confined
to the configuration surface (`config.py`, `cli.py`), one additive parameter on the
shared timestamp decode path, a declared `pyyaml` dependency, and
example/ignore/doc files. With no `config.yaml` on disk and no `VOF_TIMEZONE`/
`timezone` set, behavior is byte-for-byte identical to the delivered
`weight-body-mass` state. **This closes roadmap phase 2** (home health devices).
Implements FR-CFG-1..FR-CFG-6 and NFR-CFG-1..NFR-CFG-6.

- Added: `config.yaml` configuration source, a permanent tier of the precedence
  chain wired into `Settings` via `settings_customise_sources` in `config.py`;
  the file on disk is optional (absent = silent no-op, like a missing `.env`) and
  YAML keys are `Settings` **field names** (`hr_min`, `timezone`, ...), not
  `VOF_`-prefixed. `extra = "forbid"` still rejects unknown keys from any source,
  so an unknown YAML key or malformed/non-mapping YAML fails loudly at startup
  (FR-CFG-1, FR-CFG-2, FR-CFG-3)
- Added: `DEFAULT_CONFIG_PATH` module constant in `config.py` (`config.yaml` at the
  working directory / repo root) threaded into the YAML source
- Precedence, highest to lowest: **CLI args → environment (incl. `.env`) →
  `config.yaml` → built-in defaults**, applied per key; env (and `.env`) stay
  authoritative over YAML and CLI args stay authoritative over both, generalizing
  the existing `--adapter` override (FR-CFG-2)
- Added: `--config PATH` flag in `cli.py` selecting which file the `config.yaml`
  tier reads (default `config.yaml` at repo root, resolved via an early
  `parse_known_args` pass before `Settings` is built). An explicitly supplied
  `--config` path that does not exist **fails loud** at startup naming the path;
  a missing *default* file stays a silent no-op. No `VOF_CONFIG_FILE` env var is
  added (FR-CFG-6)
- Added: `timezone` / `VOF_TIMEZONE` setting (default `local`) in `config.py`,
  with a `resolve_timezone(name) -> ZoneInfo | None` stdlib-`zoneinfo` helper and
  a `field_validator` so an unresolvable zone fails at `Settings()` construction
  naming the value. `local` preserves today's host-local behavior (FR-CFG-4)
- Changed: `adapters/datetime_field.py` — `decode_timestamp` gains an additive,
  keyword-defaulted `tz: tzinfo | None = None` parameter. `tz=None` keeps the
  prior `naive.astimezone()` host-local result byte-for-byte; a non-`None` `tz`
  interprets the zoneless device wall-clock **as being in** that zone via
  `naive.replace(tzinfo=tz)`. `TIMESTAMP_SIZE` and the `__all__` surface are
  unchanged (FR-CFG-4, NFR-CFG-1)
- Changed: `BloodPressureMeasurementParser`, `TemperatureMeasurementParser`,
  `WeightMeasurementParser` and their `BloodPressureBleAdapter`,
  `HealthThermometerBleAdapter`, `WeightScaleBleAdapter` thread an optional
  keyword `tz` through to `decode_timestamp`; `cli.py` resolves the `tzinfo` once
  via `resolve_timezone(settings.timezone)` and passes it when building adapters.
  The no-device-timestamp `now()` fallback and the heart-rate / PLX parsers (no
  device timestamp) are untouched (FR-CFG-4, NFR-CFG-1)
- Changed: `pyproject.toml` — `pyyaml` promoted to a pinned direct dependency
  (previously transitive via `uvicorn[standard]`), needed by
  `YamlConfigSettingsSource` (NFR-CFG-4)
- Added: committed `config.yaml.example` (SPDX header as a YAML comment) listing
  the YAML-expressible settings by field name and documenting the precedence
  order, the `--config` flag, and the `timezone` key. It **omits `api_token`** and
  notes the token belongs in `.env`/env — a documentation convention, not a code
  guardrail (FR-CFG-5)
- Added: `config.yaml` to `.gitignore` so a populated runtime config is not
  committed, mirroring how `.env` is ignored while `.env.example` is tracked; and
  `VOF_TIMEZONE=local` to `.env.example` with a comment on its default and override
  (FR-CFG-5)
- No secret guardrails in code and no catch-and-soften: configuration failures
  (missing `--config` path, unknown key, malformed YAML, invalid `timezone`)
  propagate and abort startup with their underlying messages. The only secret
  protection is the pre-existing "never log configuration values" rule, which this
  slice does not weaken; no new logging of config was added (NFR-CFG-3)
- Changed: `docs/brief-config-file.md` — the Promotion section now names the
  `--config PATH` override and the fail-loud, no-secret-guardrail stance, keeps
  both drivers (length and structure) visible, and cites
  `docs/brief-validation-modes.md` as independent corroboration that flat
  `VOF_<VITAL>_<BOUND>` pairs are the wrong *shape* for planned validation-mode
  work. No EviTrace-ported or third-party code was used, so `NOTICE` is unchanged
  (NFR-CFG-4, NFR-CFG-6)

## [2026-09-23] — Body weight (spec/weight-body-mass)

Implements the fourth and final phase-2 slice: acquiring body weight over the
standard Bluetooth Weight Scale Service (WSS) Weight Measurement characteristic
(`0x2A9D`, indication-based) and representing it as a US Core Body Weight
Observation. Weight is a single scalar quantity, so it lands as a new
`ScalarVital` and reuses the existing `ScalarVitalMapper`, `BleConnection`
lifecycle, `DuplicateValidator`, `SensorContactValidator`, and per-vital-class
`PlausibleRangeValidator` unchanged — no new mapper code and no new BLE lifecycle.
Unlike the earlier slices, the weight value is a plain unit-scaled uint16 (not an
IEEE-11073 SFLOAT/FLOAT), so a dedicated scaling function is added and
`adapters/sfloat.py` is left untouched; the optional timestamp reuses the shared
`decode_timestamp` helper unchanged. All additions are additive; no existing
public ABC or exported name changed. This slice completes the phase-2 vital-sign
set (blood pressure, oxygen saturation, body temperature, body weight). Implements
FR-WT-1..FR-WT-9 and NFR-WT-1..NFR-WT-6.

- Added: `vitals/builtin/body_weight.py` — `BodyWeight`, a new concrete
  `ScalarVital` (US Core Body Weight; LOINC 29463-7; UCUM `kg`; default plausible
  range `(2.0, 650.0)` kg — physical-plausibility bounds, not clinical
  thresholds), exported from `vitals/__init__.py` under `# Concrete defaults`
  (FR-WT-1)
- Added: `adapters/weight_parser.py` — `WeightMeasurementParser` for GATT
  `0x2A9D`, with pure `parse_weight_flags`/`required_length`/`scale_weight`
  helpers and an injectable tz-aware clock. `scale_weight` applies the
  unit-dependent uint16 resolution (SI `0.005` kg vs Imperial `0.01` lb, then
  `× 0.45359237` to kilograms) chosen from the flags byte, so the constructed
  reading is always kilograms. Does **not** use `adapters/sfloat.py` (weight is
  not a medical FLOAT); reuses the shared `decode_timestamp` for the optional
  timestamp. The optional user-ID, BMI, and height fields are length-accounted
  only and never decoded, logged, or stored (FR-WT-2, FR-WT-3, NFR-WT-5)
- Added: `adapters/builtin/weight_scale_ble.py` — `WeightScaleBleAdapter`,
  composing the shared `BleConnection` for WSS service `0x181D` / characteristic
  `0x2A9D` (bleak enables the characteristic's indications transparently, so
  `BleConnection` is unchanged); `bleak` stays lazily imported inside
  `BleConnection` only (FR-WT-4, NFR-WT-1)
- Added: `adapters/builtin/mock.py` — `MockWeightAdapter` and `WeightEmissionMode`
  (`VALID`, `IMPLAUSIBLE`, `IMPERIAL_SOURCE`), emitting `BodyWeight` (always
  kilograms); never imports `bleak` (FR-WT-8)
- Added: `WeightScaleBleAdapter`, `MockWeightAdapter`, and `WeightEmissionMode` to
  `adapters/__init__.py` under `# Concrete defaults` (FR-WT-4, FR-WT-8)
- Added: `VOF_WEIGHT_MIN` / `VOF_WEIGHT_MAX` config variables (`Settings.weight_min`
  = 2.0, `Settings.weight_max` = 650.0) in `config.py` and `.env.example` (FR-WT-6)
- Changed: `cli.py` — `_resolve_adapter` maps the `weight` and `mock-weight` short
  names; `_build_orchestrator` adds a `BodyWeight` entry to the
  `PlausibleRangeValidator` per-vital-class overrides map (no validator code
  change). Mapper resolution (`BodyWeight → ScalarVitalMapper`) dispatches via the
  existing MRO registry with no orchestrator change (FR-WT-5, FR-WT-6, FR-WT-8)
- Added: `docs/protocol-weight-measurement.md` — Bluetooth SIG WSS /
  Weight Measurement citations, the SI-vs-Imperial scaling trap, the user-ID
  privacy note, and the `(2.0, 650.0)` kg range rationale (FR-WT-3, NFR-WT-4)
- Changed: `docs/device-compatibility.md` — added a standard-WSS weight-scale row,
  and a row noting proprietary-BLE body-composition scales (e.g. RENPHO Elis 1) are
  not supported here and route through the phase-3 aggregator path (FR-WT-8)
- Changed: `docs/brief-config-file.md` — added the final phase-2 config-surface
  checkpoint (the `VOF_*` surface reaches 19; 12 per-vital range keys), closing the
  phase-2 length-driver assessment with a "not promoted on length" recommendation
  (FR-WT-9)

## [2026-09-23] — Body temperature (spec/body-temperature)

Implements the third phase-2 slice: acquiring body temperature over the standard
Bluetooth Health Thermometer Service (HTS) Temperature Measurement characteristic
(`0x2A1C`, indication-based) and representing it as a US Core Body Temperature
Observation. Temperature is a single scalar quantity, so it lands as a new
`ScalarVital` and reuses the existing `ScalarVitalMapper`, `BleConnection`
lifecycle, `DuplicateValidator`, and `SensorContactValidator` unchanged — no new
mapper code and no new BLE lifecycle. Two shared-module changes land first as
guardrailed, non-breaking groundwork: an additive 32-bit FLOAT decoder and a
behavior-preserving extraction of the date-time decoder. All additions are
additive; no existing public ABC or exported name changed. Implements
FR-TEMP-1..FR-TEMP-9 and NFR-TEMP-1..NFR-TEMP-6.

- Added: `vitals/builtin/body_temperature.py` — `BodyTemperature`, a new concrete
  `ScalarVital` (US Core Body Temperature; LOINC 8310-5; UCUM `Cel`; default
  plausible range `(10.0, 47.0)` °C — physical-plausibility bounds, not clinical
  thresholds), exported from `vitals/__init__.py` under `# Concrete defaults`
  (FR-TEMP-1)
- Added: `adapters/sfloat.py` — `decode_float` (IEEE-11073 32-bit FLOAT: 8-bit
  signed exponent, 24-bit signed mantissa) plus `FLOAT_SIZE` and the
  FLOAT-specific reserved-mantissa set, alongside the existing `decode_sfloat`.
  **Additive/non-breaking** — `decode_sfloat`, its signature, its reserved set,
  and `SFLOAT_SIZE` are unchanged (FR-TEMP-2, NFR-TEMP-1)
- Added: `adapters/datetime_field.py` — the shared org.bluetooth 7-byte date-time
  decode (`decode_timestamp`, `TIMESTAMP_SIZE`) extracted from `bp_parser.py`;
  `adapters/bp_parser.py` now imports and **re-exports** `decode_timestamp` so its
  `__all__` and existing tests stay green. **Behavior-preserving/non-breaking**
  (an intra-`adapters` move; dependency directions unaffected) (FR-TEMP-3,
  NFR-TEMP-1, NFR-TEMP-2)
- Added: `adapters/temp_parser.py` — `TemperatureMeasurementParser` for GATT
  `0x2A1C`, with pure `parse_temp_flags`/`required_length`/`fahrenheit_to_celsius`
  helpers and an injectable tz-aware clock; decodes the temperature 32-bit FLOAT,
  normalizes Fahrenheit→Celsius when the unit flag is set, decodes the optional
  host-local tz-aware timestamp, length-accounts the optional temperature-type
  field, and drops malformed/short/reserved-FLOAT/invalid-timestamp payloads
  (FR-TEMP-3, FR-TEMP-2)
- Added: `adapters/builtin/thermometer_ble.py` — `HealthThermometerBleAdapter`
  (composes `BleConnection` for HTS service `0x1809` / characteristic `0x2A1C`);
  and `MockThermometerAdapter` with `ThermometerEmissionMode`
  (VALID/IMPLAUSIBLE/FAHRENHEIT_SOURCE) in `adapters/builtin/mock.py`, both
  exported from `adapters/__init__.py` under `# Concrete defaults`; neither the
  mock nor any non-BLE module imports `bleak` (FR-TEMP-4, FR-TEMP-8, NFR-TEMP-5)
- Added: config variables `VOF_TEMP_MIN` (10.0) and `VOF_TEMP_MAX` (47.0) in
  `config.py` and `.env.example`, noted as physical-plausibility bounds
  (FR-TEMP-6)
- Changed: `cli.py` — adapter short names `temp` and `mock-temp`; the scalar
  `PlausibleRangeValidator` overrides map gains a
  `BodyTemperature: (VOF_TEMP_MIN, VOF_TEMP_MAX)` entry, applied only to
  body-temperature readings with no cross-application to other vitals; no
  validator or orchestrator code change (`BodyTemperature → ScalarVitalMapper`
  resolves via the existing MRO registry) (FR-TEMP-8, FR-TEMP-6, FR-TEMP-5)
- Added: `docs/protocol-body-temperature-measurement.md` citing the Bluetooth SIG
  Health Thermometer Service / Temperature Measurement (`0x2A1C`) and ISO/IEEE
  11073-20601 32-bit FLOAT specifications, with a range-rationale note recording
  the evidence behind the `(10.0, 47.0)` °C bounds; standard-thermometer row added
  to `docs/device-compatibility.md` (FR-TEMP-3, FR-TEMP-1, FR-TEMP-8, NFR-TEMP-4)
- Added: `docs/brief-validation-modes.md` — idea-only brief on personal/clinical
  validation modes (flag, never drop), distinct from the wide physics-based
  plausibility bounds; `docs/brief-config-file.md` — added the post-temperature
  surface-size checkpoint (`VOF_*` count now 17; flat list judged not yet
  "awkward") plus a structural-driver note that per-vital validation modes push
  toward `config.yaml` independently of list length (FR-TEMP-9)

## [2026-09-23] — Oxygen saturation (spec/oxygen-saturation)

Implements the second phase-2 slice: acquiring peripheral oxygen saturation
(SpO2) over the standard Bluetooth Pulse Oximeter (PLX) Continuous Measurement
characteristic and representing it as a US Core Pulse Oximetry Observation. SpO2
is a single scalar percentage, so it lands as a new `ScalarVital` and reuses the
existing `ScalarVitalMapper` and `BleConnection` lifecycle unchanged — no new
mapper code and no new BLE lifecycle. All additions are additive; no existing
public ABC or exported name changed. Implements FR-SPO2-1..FR-SPO2-8 and
NFR-SPO2-1..NFR-SPO2-6.

- Added: `vitals/builtin/oxygen_saturation.py` — `OxygenSaturation`, a new
  concrete `ScalarVital` (US Core Pulse Oximetry; LOINC 59408-5; UCUM `%`;
  default plausible range 70–100%), exported from `vitals/__init__.py` under
  `# Concrete defaults` (FR-SPO2-1)
- Added: `adapters/sfloat.py` — shared IEEE-11073 16-bit SFLOAT decoding
  (`decode_sfloat`, `SFLOAT_SIZE`, reserved-mantissa set) as pure functions;
  `adapters/bp_parser.py` refactored to import it instead of defining its own
  (behavior-preserving — the existing BP SFLOAT tests are the guardrail)
  (FR-SPO2-2)
- Added: `adapters/plx_parser.py` — `PlxContinuousMeasurementParser` for GATT
  `0x2A5F`, with pure `parse_plx_flags`/`required_length` helpers and an
  injectable tz-aware clock; decodes only the SpO2 SFLOAT, length-accounts the
  optional pulse-rate and status fields, and drops malformed/short/reserved
  payloads (FR-SPO2-3)
- Added: `adapters/builtin/pulse_oximeter_ble.py` — `PulseOximeterBleAdapter`
  (composes `BleConnection` for PLX service `0x1822` / characteristic `0x2A5F`);
  and `MockOximeterAdapter` with `OximeterEmissionMode` in
  `adapters/builtin/mock.py`, both exported from `adapters/__init__.py` under
  `# Concrete defaults` (FR-SPO2-4, FR-SPO2-8)
- Changed: `validation/builtin/validators.py` — generalized
  `PlausibleRangeValidator` to per-vital-class bounds via a new `overrides=`
  keyword (`dict[type, tuple[float, float]]`); the legacy `(hr_min, hr_max)`
  positional form still works (mapped internally to a `HeartRate` override), so
  the change is backward compatible and does not touch the `Validator` ABC
  (FR-SPO2-6, NFR-SPO2-1)
- Changed: `fhir/mappers.py` — `ScalarVitalMapper` now sets
  `valueQuantity.unit` from the vital's `ucum_unit` (dropping the HR-specific
  `_VALUE_UNIT_DISPLAY = "beats/minute"` constant) so SpO2 displays `%`; as a
  side effect HR Observations now show `unit: "/min"` instead of
  `"beats/minute"` (non-breaking — the UCUM `code` is unchanged and remains
  authoritative). `OxygenSaturation` resolves to `ScalarVitalMapper` via the
  existing MRO registry with no registration change (FR-SPO2-5, NFR-SPO2-3)
- Added: config variables `VOF_SPO2_MIN` (70) and `VOF_SPO2_MAX` (100) in
  `config.py` and `.env.example` (FR-SPO2-6)
- Changed: `cli.py` — adapter short names `spo2` and `mock-spo2`; the scalar
  `PlausibleRangeValidator` is now wired with an explicit per-class overrides
  map (`HeartRate` from `VOF_HR_*`, `OxygenSaturation` from `VOF_SPO2_*`),
  replacing the positional HR construction (FR-SPO2-8, FR-SPO2-6)
- Added: `docs/protocol-pulse-oximeter-measurement.md` citing the Bluetooth SIG
  Pulse Oximeter Service / PLX Continuous Measurement (`0x2A5F`) and IEEE-11073
  SFLOAT specifications; standard pulse-oximeter row added to
  `docs/device-compatibility.md` (FR-SPO2-3, NFR-SPO2-4)
- Changed: `docs/brief-config-file.md` — added the post-SpO2 surface-size
  checkpoint (`VOF_*` count now 15; flat list judged not yet "awkward")

## [2026-09-23] — Blood pressure (spec/home-health-devices)

Implements the first phase-2 slice: acquiring blood pressure over the standard
Bluetooth Blood Pressure Service and representing it as a US Core Blood Pressure
Observation. Adds the first concrete `ComponentVital`, activates the
`ComponentVitalMapper`, and extracts a reusable BLE lifecycle so heart rate and
blood pressure share one connection implementation. All additions are additive —
no existing public ABC or exported name changed. Implements FR-HH-1..FR-HH-9 and
NFR-HH-1..NFR-HH-6.

- Added: `vitals/base.py` — `ComponentSpec` value object and the concrete
  `ComponentVital` shape (`components` class metadata + `component_values()`),
  with import-time metadata enforcement (FR-HH-1)
- Added: `vitals/builtin/blood_pressure.py` — `BloodPressure`, the first concrete
  `ComponentVital` (panel LOINC 85354-9; systolic 8480-6 and diastolic 8462-4 in
  `mm[Hg]`; no mean arterial pressure) (FR-HH-2)
- Changed: `adapters/ble.py` — extracted the profile-agnostic BLE lifecycle into a
  reusable `BleConnection` used by composition; `BleHeartRateAdapter` now delegates
  to it with its public surface unchanged (FR-HH-4, NFR-HH-1)
- Added: `adapters/bp_parser.py` — `BloodPressureMeasurementParser` for GATT
  `0x2A35`, with pure IEEE-11073 SFLOAT decoding, flags/length accounting, kPa→mmHg
  normalization, and local-time timestamp decoding; malformed payloads dropped
  (FR-HH-5, FR-HH-6)
- Added: `adapters/builtin/blood_pressure_ble.py` — `BloodPressureBleAdapter`
  (composes `BleConnection` for Blood Pressure Service `0x1810`); and
  `MockBloodPressureAdapter` with `BloodPressureEmissionMode` in
  `adapters/builtin/mock.py` (FR-HH-4, FR-HH-9)
- Changed: `fhir/mappers.py` — implemented `ComponentVitalMapper.to_observation`
  (values in `component` entries, no panel `valueQuantity`); registered it for
  `ComponentVital` in `fhir/__init__.py` (FR-HH-3, FR-HH-8, NFR-HH-3)
- Added: `validation/builtin/validators.py` — `ComponentRangeValidator`;
  generalized `DuplicateValidator` identity to component vitals (guards
  store-and-forward re-sends) (FR-HH-7)
- Added: config variables `VOF_BP_SYSTOLIC_MIN`, `VOF_BP_SYSTOLIC_MAX`,
  `VOF_BP_DIASTOLIC_MIN`, `VOF_BP_DIASTOLIC_MAX` (FR-HH-7)
- Changed: `cli.py` — adapter short names `bp` and `mock-bp`; component range
  validator wired from the `VOF_BP_*` bounds (FR-HH-9)
- Added: `docs/protocol-blood-pressure-measurement.md` citing the Bluetooth SIG
  Blood Pressure Service / Measurement (`0x2A35`) and IEEE-11073 SFLOAT
  specifications; BP-cuff row added to `docs/device-compatibility.md` (FR-HH-5,
  NFR-HH-4)

## [2026-09-23] — Open roadmap phase 2 (home health devices)

Records the deliberate scope decision to promote roadmap phase 2 — home health
devices via standard Bluetooth health profiles — from context-only to active
work, now that the heart-rate MVP is complete and all CI gates pass. This is a
scope decision, not an automatic consequence of finishing the MVP.

- Added: `docs/adr-0001-open-phase-2-home-health-devices.md` — accepted ADR
  documenting the decision, rationale, resolved design decisions, and the
  per-profile sibling-spec delivery plan.
- Changed: `.kiro/steering/product.md` — roadmap marks phase 1 delivered and
  phase 2 active; the out-of-scope list now separates "out of MVP scope,
  delivered later" from "permanently out of scope".
- Scope opened: phase 2 delivered as one sibling spec per profile. The first
  (`home-health-devices`) covers blood pressure only — the first concrete
  `ComponentVital`, a reusable BLE lifecycle extracted by composition, and
  store-and-forward readings. SpO2, temperature, and weight follow as sibling
  specs.
- Phases 3–5 (phone aggregators, persistence/outbound/SMART on FHIR, separately
  licensed adapters) remain closed and context-only.

## [2026-09-23] — Load configuration from `.env`

Fixed startup failure where `Settings` ignored the `.env` file, causing a required-field
`ValidationError` for `api_token` even after following the documented `cp .env.example .env`
setup flow.

- Changed: `config.py` — `Settings.model_config` now sets `env_file=".env"` (UTF-8), so
  `VOF_*` values in `.env` are loaded. Real environment variables still take precedence.
- Added: `tests/test_config.py` — regression coverage for `.env` loading, field defaults,
  process-env precedence, and the required-token failure path.

## [2026-09-23] — Heart rate pipeline MVP (spec/hr-pipeline)

Fills in the business logic behind the scaffold stubs so the heart-rate MVP runs end to end:
BLE and mock acquisition, payload parsing, validation, FHIR mapping, in-memory storage, a
read-only FHIR REST API with token auth, and a live WebSocket dashboard. Implements FR-1..FR-12
and NFR-1..NFR-6.

- Added: `adapters/parser.py` — `HeartRateMeasurementParser` plus pure decoding functions
  (`parse_flags`, `hr_value_size`, `required_length`, `decode_hr_value`, `decode_sensor_contact`)
  for the Bluetooth Heart Rate Measurement characteristic `0x2A37` (FR-3a)
- Added: `adapters/builtin/mock.py` — `MockAdapter` with `VALID`/`IMPLAUSIBLE`/`NO_SENSOR_CONTACT`
  emission modes, no `bleak` dependency (FR-9)
- Added: `adapters/ble.py` — `BleHeartRateAdapter` connection/subscribe/reconnect lifecycle with
  lazy `bleak` import; `adapters/builtin/miband10.py` — `MiBand10Adapter` (FR-1, FR-2, FR-6, NFR-2)
- Added: `validation/builtin/validators.py` usage via `ValidatorChain` —
  `PlausibleRangeValidator`, `SensorContactValidator`, `DuplicateValidator` (FR-3b)
- Added: `fhir/builders.py` (`build_device`, `build_patient`, `build_capability_statement`,
  `build_operation_outcome`), `fhir/mappers.py` — `ScalarVitalMapper`, and `ScalarVital` mapper
  registration in `fhir/__init__.py` resolved via MRO (FR-4, NFR-4)
- Added: `store/memory.py` — `InMemoryObservationStore`, a bounded `ObservationStore` and
  `ObservationSink` returning deep-copied snapshots (FR-STORE, FR-8)
- Added: `pipeline/orchestrator.py` — `Orchestrator` wiring adapter → `ValidatorChain` → mapper →
  sinks with per-sink isolation and value-free `INFO` rejection logging (FR-ORCH, NFR-5)
- Added: `api/auth.py` — `StaticTokenAuthenticator` (constant-time `hmac.compare_digest`);
  `api/routes.py` — read-only FHIR endpoints (`GET /fhir/metadata`, `GET /fhir/Observation`,
  `GET /fhir/Observation/{id}`, `GET /fhir/Patient/{id}`, `GET /fhir/Device/{id}`) returning
  `application/fhir+json`; `api/app.py` — `create_app` factory with dashboard WebSocket
  (FR-11, FR-12, NFR-5)
- Added: `dashboard/broadcaster.py` — `DashboardBroadcaster` (`ObservationSink` + WebSocket push)
  and `dashboard/static/` (`index.html`, `style.css`, `app.js`, no build step) (FR-5, FR-6, FR-7,
  FR-10, NFR-3)
- Added: `cli.py` — composition root wiring adapter selection, `ValidatorChain`, store, broadcaster,
  orchestrator, and app under a single `asyncio.run`; binds `VOF_HOST`/`VOF_PORT` (FR-ORCH, NFR-5)
- Uses config variables `VOF_HR_MIN`, `VOF_HR_MAX`, `VOF_PATIENT_ID`, `VOF_STORE_MAX`, `VOF_ADAPTER`,
  `VOF_DEVICE_NAME`, `VOF_API_TOKEN`, `VOF_HOST`, `VOF_PORT`
- Added: `docs/protocol-heart-rate-measurement.md` citing the Bluetooth SIG Heart Rate Service /
  Heart Rate Measurement (`0x2A37`) specification used for the parser (FR-3a)

## [2026-09-21] — Repository scaffold (spec/repo-scaffold)

Creates the complete skeleton of the vitals-on-fhir repository: all packages,
module stubs, configuration, tooling, and top-level files. No business logic
is implemented; all modules contain only correct signatures and `...` bodies.

- Added: full `src/vitals_on_fhir/` package tree (stubs only)
- Added: `tests/` skeleton with `test_dependency_directions.py` (AST-based enforcement)
- Added: `pyproject.toml` with ruff, mypy strict, pytest, and uv configuration
- Added: `config.py` — `Settings` with all `VOF_*` variables
- Added: `cli.py` — composition root stub
- Added: `.env.example` listing all configuration variables
- Added: `.github/workflows/ci.yml` — four-step CI pipeline
- Ported `test_dependency_directions.py` pattern from EviTrace (GPL-3.0); recorded in NOTICE.

## [2026-09-21] — Steering layer

Added eight steering documents under `.kiro/steering/` establishing the authoritative rules
for all future spec-driven work: product scope, technical stack, project structure, object model,
FHIR conventions, security and provenance, testing strategy, and changelog policy.

- Added: `.kiro/steering/product.md` — mission, FR/NFR IDs, use cases, MVP scope, roadmap
- Added: `.kiro/steering/tech.md` — stack, commands, config variables, async and coding conventions, CI
- Added: `.kiro/steering/structure.md` — directory layout, module responsibilities, dependency-direction rules, naming conventions
- Added: `.kiro/steering/object-model.md` — full ABC hierarchy, OOP conventions, extension recipes
- Added: `.kiro/steering/fhir-conventions.md` — FHIR version, canonical Observation shape, mapping rules, Bundle/search, OperationOutcome
- Added: `.kiro/steering/security-privacy.md` — auth rules, secret handling, logging restrictions, BLE disclaimer, HIPAA statement, legal and provenance rules
- Added: `.kiro/steering/testing.md` — test strategy, contract tests, Hypothesis property tests, payload fixtures, hardware marker
- Added: `.kiro/steering/changelog-rules.md` — entry format, when to add/skip, agent responsibility
