# SCION-CENTRALIZED-CAPABILITIES — Centralized connector capabilities

Owner: scion-sdk. Cross-repo IDs: none.
Public provenance: operator request of 2026-10-22 to track everything the SDK centralizes for connectors.

## Purpose and user stories

A connector author must know which capabilities the SDK provides and which code the connector must not write. A reviewer must find the owning requirement for each capability in one place. This spec is that index. The index lists 40 capabilities. Each has an owner row, a module or extra, a rule for connectors, and a conformance method.

## Requirements and acceptance

- FR-001: Each row `SCION-CENTRALIZED-CAPABILITIES-R001` to `SCION-CENTRALIZED-CAPABILITIES-R040` says connectors use one SDK capability and ship no copy.
- FR-002: The index in `plan.md` names the owner row, the module or extra, and the conformance method of each row. A missing method reads "unchecked".
- SC-001: Every module path in the index exists in the package, and every owner row ID exists in a `requirements.md` file.
- SC-002: Every key in `[project.optional-dependencies]` appears in at least one row.

## Why a new spec

Search: `grep -rn` over `specs/` for each module and capability term. The specs read were `SCION-CONNECTOR-CONTROL`, `SCION-SOURCE-INGEST`, `SCION-FINANCE-SOURCES`, `SCION-GOVERNED-WRITEBACK`, `SCION-SCM`, `SCION-REPOSITORY-TRANSPORT`, and `SCION-OBSERVABILITY-FEEDS`. Each owns the contract of its capability. No spec lists the capabilities together or states the rule that connectors reuse them. Five capabilities had no owner: pagination, rate limiting, error redaction, the extras rule, and the earth-observation records. This spec owns those rows. It extends no existing row. It adds no contract that an owner row already states.

## Scope and interfaces

Owned behavior: the connector-facing rule for each capability. The owner rows keep the contracts. Dependencies: the owner rows listed in `plan.md`. GraphQL builds on `SCION-CONNECTOR-CONTROL-R014.12`, which another lane extends. Connector identity is `SCION-CONNECTOR-CONTROL-R071`.

Non-goals: a fleet-wide scan. Row `SCION-CENTRALIZED-CAPABILITIES-R025` adds the `vector` and `vector-chroma` extras for vector-store clients. Row `SCION-CENTRALIZED-CAPABILITIES-R005` adds the shared request limiter `RateLimiter`.

## Traceability

| Requirement | Design section | Test ID | Evidence |
|---|---|---|---|
| FR-001 | plan.md Capability index | CC-01 to CC-40 |  |
| FR-002 | plan.md Capability index | CC-01 to CC-40 |  |
| SC-001 | plan.md Live integration path | CC-01 to CC-40 |  |
| SC-002 | plan.md Interfaces and data model | CC-40, CC-41 |  |

## Open questions

None.
