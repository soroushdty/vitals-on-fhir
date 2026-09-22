---
inclusion: always
---

# Security and privacy — vitals-on-fhir

## Authentication

- Every HTTP API request and every WebSocket connection (dashboard) requires a valid bearer token.
- The token is set via `VOF_API_TOKEN` and compared using constant-time comparison (`hmac.compare_digest` or equivalent). Never use `==` for token comparison.
- Missing or invalid tokens must be rejected with HTTP 401 and a FHIR `OperationOutcome` (issue code `"security"`). Do not return 403 — the client has not authenticated.
- `StaticTokenAuthenticator` is the MVP implementation. SMART on FHIR is a roadmap item; do not stub or reference it in the MVP code.

## Network binding

- The service binds to `127.0.0.1` by default (`VOF_HOST`). This is a security default, not a convenience default. Remote access is a roadmap item; the MVP must not be exposed to untrusted networks.
- Do not document or imply remote deployment in any MVP-era UI, README section, or dashboard text.
- `VOF_HOST` may be overridden (e.g. for local LAN testing), but users must opt in explicitly.

## Secret handling

Rules that apply to all code in this repository:

- `VOF_API_TOKEN` must never appear in any log message at any level, in any exception message, in any error response body, or in any comment or test fixture that is committed to the repository.
- No secrets in source code. Use `.env` loaded at runtime; never hardcode token values.
- Never commit a populated `.env` file. The `.env.example` must contain only placeholder values (e.g. `VOF_API_TOKEN=change-me`).
- In tests, use a synthetic token value (e.g. `"test-token-do-not-use"`) — never a real credential.
- Do not log config values at startup even at `DEBUG` level (they may contain the token).

## Logging restrictions

- Measurement values (heart-rate numbers) must not appear in log messages at `INFO` level or above (NFR-5). They may appear at `DEBUG`.
- Secrets must not appear at any log level.
- Log at `INFO`: connection events (connected, disconnected, reconnecting), validation rejections (without the rejected value), startup/shutdown.
- Log at `DEBUG`: parsed payloads, raw bytes, detailed state transitions.
- Log at `ERROR`: resource construction failures, unhandled exceptions at the orchestrator boundary.
- Use `logging.getLogger(__name__)` in every module. Never use the root logger directly.

## BLE broadcast and the unauthenticated channel

The Bluetooth Heart Rate Service (`0x180D`) is **unauthenticated**: when broadcast is enabled on the device, any nearby Bluetooth LE observer can read the heart-rate stream. This is inherent to the protocol and cannot be changed by this software.

- Document this limitation clearly in the README and in the dashboard UI.
- Do not attempt to add BLE-level authentication or encryption — the standard channel does not support it.
- Advise users to disable HR broadcast on the device when the monitoring session is not in use.

## Data storage and retention

- Observations are kept **in memory only** during the MVP. They are lost on process restart. There is no disk persistence, no database, and no remote storage.
- `VOF_STORE_MAX` (default 10,000) bounds the number of Observations retained. Oldest entries are evicted when the bound is reached.
- No patient-identifying information is persisted between sessions. `VOF_PATIENT_ID` is a local synthetic identifier, not a real patient identifier.

## Not HIPAA-compliant / not for real patient data

vitals-on-fhir is a research and educational proof-of-concept. It:

- is not designed for exposure to untrusted networks,
- does not implement audit logging, access controls, or data-at-rest encryption,
- is not HIPAA-compliant,
- must not be used with real patient data in any production or clinical setting.

This statement must remain in the README and must be referenced in any user-facing documentation.

## Legal and provenance rules

### License

- The entire project is licensed AGPL-3.0-or-later.
- Every new source file must carry the SPDX header as its first non-shebang line:
  ```python
  # SPDX-License-Identifier: AGPL-3.0-or-later
  ```
- If you modify vitals-on-fhir and make it available to users over a network, AGPL requires you to offer them the corresponding source code.

### Protocol knowledge sourcing

- Do not copy, translate, or closely paraphrase code from other projects, including Gadgetbridge and vendor SDKs.
- Protocol knowledge (BLE characteristic formats, GATT service UUIDs) must come only from:
  - Published Bluetooth SIG specifications
  - HL7/FHIR published specifications and IGs
  - Public vendor documentation
  - The team's own packet captures
- All protocol sources must be cited in `docs/`. The citation must include the specification name, version, and URL or publication date.

### EviTrace exception

Code and patterns may be ported from [EviTrace](https://github.com/soroushdty/EviTrace) (GPL-3.0), whose sole author is a maintainer of this project. Requirements when porting:

1. Add a header comment to the ported file identifying the origin:
   ```python
   # Ported from EviTrace (https://github.com/soroushdty/EviTrace), GPL-3.0
   # Original author: Soroush Dianaty
   ```
2. Record the ported file in `NOTICE` with: source project name, license, URL, and the path(s) of files in this repository that contain ported material.
3. The GPL-3.0 origin is compatible with AGPL-3.0-or-later; the repository license covers the whole.

Known EviTrace candidates: the AST dependency-direction test, changelog rules, and testing conventions (property-based testing patterns, hardware marker).

### Third-party code (general)

Any other third-party code that is deliberately included must:
- Be under a license compatible with AGPL-3.0-or-later.
- Keep its original copyright notices and license text.
- Be recorded in `NOTICE` with the same fields as the EviTrace entry above.

### Trademark use

- HL7® and FHIR® are registered trademarks of Health Level Seven International. This project is not affiliated with or endorsed by HL7.
- Device and brand names (Xiaomi, Mi Band, etc.) are used only to describe compatibility. They do not imply endorsement.
- Use HL7/FHIR and device trademarks only descriptively; do not use them in the package name, PyPI metadata, or any way that implies official affiliation.

### No circumvention

Do not implement, document, or reference:
- Circumvention of device authentication or encryption
- Extraction of keys or credentials from vendor apps or firmware
- Use of proprietary or reverse-engineered protocols
