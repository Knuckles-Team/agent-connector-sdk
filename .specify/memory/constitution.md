# Scion SDK constitution

This repository inherits the [organization constitution](https://github.com/Knuckles-Team/pipelines/blob/main/.specify/memory/constitution.md) version 1.0.0. Every article of that constitution applies here. This file adds only the rules and limits of this repository.

**Inherits**: organization constitution v1.0.0 | **Version**: 1.0.0 | **Ratified**: 2026-10-31 | **Last amended**: 2026-10-31

## Organization standards

- [Spec standard](https://github.com/Knuckles-Team/pipelines/blob/main/reference/spec-standard.md): one owning spec per capability, computed states, `Spec:` trailers.
- [Ecosystem boundaries](https://github.com/Knuckles-Team/pipelines/blob/main/reference/ecosystem-boundaries.md): which repository owns which requirement.
- [Wording standard](https://github.com/Knuckles-Team/pipelines/blob/main/reference/ste.md): sentences of 20 words or fewer, with `must`, `should`, or `may`.

## Repository articles

### R-I. The SDK owns connector contracts and transports

The SDK owns connector contracts, transports, the engine client adapter and ontology pack generation. A shared connector capability is implemented here once, never in a connector.

**Enforced by:** [Ecosystem boundaries](https://github.com/Knuckles-Team/pipelines/blob/main/reference/ecosystem-boundaries.md), SDK row; `sdk-conformance` in downstream connectors.

**Plan check:** Does the change add the capability here, as one component that connectors reuse?

### R-II. The public API is tested and reachable

Every public symbol has a test and a production caller. An orphan module fails the gate.

**Enforced by:** Pre-commit hooks `check-orphan-modules` and `check-public-api-tested` (`scripts/check_wiring.py`).

**Plan check:** Does each new public symbol have a test and a caller?

### R-III. The engine graph contract is external and documented without private data

The SDK reads the engine graph contract from the published package and keeps documentation free of private data.

**Enforced by:** Pre-commit hooks `check-external-graph-contract` and `check-documentation-privacy`.

**Plan check:** Does the change read the engine contract only from the published package?

## Repository limits

This repository uses the organization KISS limits unchanged (`.config/kiss.toml`).

Amend this file in a reviewed change. State the impact in the pull request. When the organization constitution changes its version, update the **Inherits** line in the same change.
