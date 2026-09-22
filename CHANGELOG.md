# Changelog

All significant changes to vitals-on-fhir are recorded here.
This file is permanent and is never truncated or rewritten. See `changelog-rules.md` for the entry format and policy.

---

## [2026-09] — Steering layer

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
