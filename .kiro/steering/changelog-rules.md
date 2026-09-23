---
inclusion: always
---

# Changelog rules — vitals-on-fhir

`CHANGELOG.md` is a permanent record. It is never truncated, summarized, or rewritten. Entries are prepended (newest at the top).

## When to add an entry

Add an entry when:
- A spec is implemented (fully or partially, if the partial result is mergeable)
- A steering document is created or significantly changed
- The README is significantly rewritten
- Modules are renamed or moved
- Public APIs or ABCs change (method signatures, added/removed abstract methods, renamed classes in `__all__`)
- Config variables are added, renamed, or removed
- The dependency-direction rules change
- Third-party code is ported into the repository (cite in NOTICE too)

Skip entries for:
- Routine bug fixes that don't touch public APIs
- Docstring edits
- Formatting-only changes
- Internal refactors that leave all public APIs unchanged
- Adding or changing tests (unless a test file is itself part of the public contract, like `test_dependency_directions.py`)

## Entry format

```markdown
## [YYYY-MM-DD] — Short title (spec/<name> if applicable)

One or two sentences summarizing what changed and why.

- Bullet: specific change
- Bullet: another specific change
- Bullet: migration note if consumers are affected
```

Rules:
- Date is `YYYY-MM-DD` (day granularity; no time of day). Git history is the authoritative sub-day timeline — the changelog date is a human-readable marker and should be taken from the entry's merge/commit date, not the wall clock.
- Title is short (≤ 60 characters). If the entry corresponds to a completed spec, append `(spec/<spec-name>)`.
- The prose sentence(s) describe the change at the level of "what and why", not "how".
- Bullets are specific: name the class, variable, or endpoint that changed. Avoid generic bullets like "updated code".
- If a public API change is breaking, add a `**Breaking:**` prefix to the relevant bullet.
- If third-party code is ported, include a bullet: `Ported <thing> from <project> (<license>); recorded in NOTICE.`

## Example entries

```markdown
## [2026-09-21] — Steering layer (spec/steering)

Added eight steering documents under `.kiro/steering/` covering product scope, architecture,
FHIR conventions, security, testing strategy, and changelog rules.

- Added: `product.md`, `tech.md`, `structure.md`, `object-model.md`
- Added: `fhir-conventions.md`, `security-privacy.md`, `testing.md`, `changelog-rules.md`
- Ported AST dependency-direction test pattern from EviTrace (GPL-3.0); recorded in NOTICE.

## [2026-09-23] — Heart rate pipeline MVP (spec/hr-pipeline)

Implements FR-1 through FR-10: BLE acquisition, validation, FHIR mapping, in-memory store,
read-only FHIR API, and live WebSocket dashboard.

- Added: `vitals/builtin/heart_rate.py` — `HeartRate` concrete class
- Added: `adapters/builtin/miband10.py` — `MiBand10Adapter`
- Added: `adapters/builtin/mock.py` — `MockAdapter`
- Added: `store/memory.py` — `InMemoryObservationStore`
- Added: `api/routes.py` — read-only FHIR REST endpoints
- Added: `VOF_HR_MIN`, `VOF_HR_MAX` config variables
```

## Responsibility

The agent implementing a spec adds the `CHANGELOG.md` entry as part of that spec's final task. The entry is not optional and is not deferred to a separate cleanup task.
