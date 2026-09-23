# vitals-on-fhir

**Consumer wearables and home health devices → HL7® FHIR® R4.**

> **Status:** early development (spec-driven). Commands, endpoints, and class names may change until the first release.

> **Not a medical device.** A research and educational proof-of-concept for healthcare interoperability. Not for diagnosis, treatment, or any clinical decision-making.

## What is this?

Most wearables lock their data inside proprietary apps and clouds, yet many can speak open Bluetooth standards. `vitals-on-fhir` acquires vital signs from those open channels and exposes them as standards-compliant HL7 FHIR R4 Observations. Any FHIR-capable system (an EHR sandbox, a research pipeline, a caregiver dashboard) can then consume patient-generated vital signs without device-specific integrations. The project focuses on the bridge; downstream apps and analytics are left to whoever consumes the FHIR API.

The MVP acquires real-time heart rate via the standard Bluetooth Heart Rate Service (GATT `0x180D`), one device at a time.

## Quick start

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/), and a Bluetooth LE adapter (only for real devices; the mock adapter needs none, and the Bluetooth library isn't even loaded).

```bash
git clone https://github.com/soroushdty/vitals-on-fhir.git
cd vitals-on-fhir
uv sync
cp .env.example .env          # then set VOF_API_TOKEN
```

**Run with simulated data (no device needed):**

```bash
uv run vitals-on-fhir --adapter mock
```

### Using the MVP

Once the service is running, open **`http://127.0.0.1:8000/`** in a browser, enter your `VOF_API_TOKEN`, and you'll see the live heart rate, the observation timestamp, and the connection status update in real time.

**Run with a Xiaomi Smart Band 10:**

1. Enable heart-rate broadcast on the band (a heart-rate sharing setting; its location varies by firmware).
2. Make sure the band isn't connected to another app that holds its only BLE connection.
3. Start the service:

```bash
uv run vitals-on-fhir --adapter miband10
```

**Run with a third-party adapter** by passing its fully qualified class path:

```bash
uv run vitals-on-fhir --adapter mypackage.adapters.MyStrapAdapter
```

## FHIR API

A local, **read-only** FHIR REST API serves the stored Observations. Every request requires `Authorization: Bearer <token>`, responses use `application/fhir+json`, and search results are FHIR `Bundle`s (`type: searchset`).

```bash
curl -H "Authorization: Bearer $VOF_API_TOKEN" \
  "http://localhost:8000/fhir/Observation?code=http://loinc.org|8867-4&_sort=-date&_count=10"
```

See [docs/fhir-api.md](docs/fhir-api.md) for the full endpoint reference and an example Observation.

## Configuration

Configuration comes from environment variables (or `.env`). Unknown `VOF_*` variables are rejected at startup to catch typos.

| Variable | Default | Description |
|---|---|---|
| `VOF_API_TOKEN` | *(required)* | Token for the API and dashboard |
| `VOF_HOST` | `127.0.0.1` | Bind address. Localhost by default |
| `VOF_PORT` | `8000` | HTTP port |
| `VOF_ADAPTER` | `mock` | `mock`, `miband10`, or a fully qualified class path (`package.module.ClassName`) |
| `VOF_DEVICE_NAME` | *(none)* | Optional BLE name filter for device discovery |
| `VOF_HR_MIN` / `VOF_HR_MAX` | `20` / `250` | Override the heart-rate plausibility range (bpm) |
| `VOF_PATIENT_ID` | `local-patient` | ID of the local Patient resource |
| `VOF_STORE_MAX` | `10000` | Maximum Observations kept in memory |

## Development

```bash
uv run pytest                  # fast suite (no hardware required)
uv run pytest -m hardware      # tests that need a real device
uv run ruff check .            # lint
uv run ruff format .           # format
uv run mypy src                # type check
```

- **CI** (GitHub Actions) runs lint, type checks, and the fast test suite on every push and pull request.
- **Architecture is enforced by tests**, not just documentation (for example, adapters may not import FHIR code).
- **`CHANGELOG.md`** records significant changes: implemented specs, public API changes, config changes, and steering updates.

See [docs/architecture.md](docs/architecture.md) for how the pipeline works, the extension points, and the project structure.

## Documentation

- [docs/architecture.md](docs/architecture.md) — how it works, extension points, and project structure
- [docs/fhir-api.md](docs/fhir-api.md) — read-only FHIR API reference and example Observation
- [docs/device-compatibility.md](docs/device-compatibility.md) — supported devices and standard-channel limitations
- [docs/roadmap.md](docs/roadmap.md) — planned vital signs, adapters, and integrations
- [docs/standards-and-related-work.md](docs/standards-and-related-work.md) — standards used and related projects
- [docs/](docs/) — SRS, decisions, and protocol source citations

## Security & privacy

- The API and dashboard require a bearer token. The service binds to `127.0.0.1` by default.
- Observations are kept **in memory only** in the MVP and are lost on restart.
- The Bluetooth Heart Rate Service is **unauthenticated**: while broadcast is enabled, any nearby device can read the heart-rate stream. Disable broadcast when not in use.
- The MVP is not designed for exposure to untrusted networks and is not HIPAA-compliant. Don't use it with real patient data in production settings.

## Academic context

This project started as a team project for **BMI 540** in the Biomedical Informatics and Data Science program at Arizona State University. A preprint is planned.

**Team:** `Soroush Dianaty, MD`, `Nusrat Ashrafi, MS`, `Isha Uttham, BS`
**Instructor:** `Shetty Sheetal, PhD`

## Contributing

Contributions are welcome. Please open an issue before starting significant work, and add a `CHANGELOG.md` entry for any change to public APIs, configuration, or architecture. By contributing, you agree that your contributions are licensed under AGPL-3.0. Include attribution and license information for any third-party code.

## Acknowledgments

Some architectural patterns and test utilities are adapted from [EviTrace](https://github.com/soroushdty/EviTrace) (GPL-3.0) by the same author. See [`NOTICE`](NOTICE).

## License

Licensed under the [GNU Affero General Public License v3.0](LICENSE). If you modify `vitals-on-fhir` and make it available to users over a network, you must offer them the corresponding source code.

HL7® and FHIR® are registered trademarks of Health Level Seven International. This project is not affiliated with or endorsed by HL7. Device names are used only to describe compatibility and do not imply endorsement.
