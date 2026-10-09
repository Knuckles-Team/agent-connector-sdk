---
name: agent-connector-sdk-development
domain: development
skill_type: skill
description: >-
  Develop, test, and release a change in agent-connector-sdk: the connector
  control and transport layer every MCP connector builds on. Use when adding
  or changing a connector manifest, a typed port implementation, a source
  adapter, an artifact kind, a transport, a sink, or anything under
  agent_connector_sdk/, and when running or releasing this repository's gates.
license: MIT
tags: [agent-connector-sdk, development, connectors, mcp, manifest, gates]
metadata:
  version: '0.1.0'
---

# agent-connector-sdk development

`agent-connector-sdk` is the connector control and transport layer: secure
FastMCP server construction, connector manifests and content publication,
typed extension ports, discovery/certification, and governed HTTP/TLS/
credential handling. It does not own vendor API implementations, durable graph
storage, ontology reasoning, agents, or workflow orchestration — those belong
to the owning connector, `epistemic-graph`, and the agent control plane.
`agent-utilities` is not a dependency of this package; keep dependency
direction enforceable by the `phase-direction` gate.

## Rapid delivery: the 5-minute contract

Specs are already designed. The work is implementation, delivered in very small, continuously landed slices.

**Time and size**
- One agent delivers one PR in 5 minutes or less. No agent or sub-agent runs longer than 5 minutes; an orchestrator dispatches the next slice to a fresh agent.
- CI turns around in 5 minutes or less. PR CI runs the fast subset: lint, type check, the spec check, and only the tests and crates the diff touches. Pushes to main run the full suite.
- Never spawn sub-agents from a delivery agent.

**Investigation budget**
- At most 2 minutes and about 10 tool calls of reading before the first edit, and at most about 25 tool calls per PR.
- If the change is not clear by then, ship the `.1` slice (typed model plus refusal test) or skip the row with a one-line note. Do not write deferral essays.
- Trust the orchestrator's evidence and ID list; do not re-verify it.

**Sizing (deterministic)**
- Split a requirement when its size score is above 6, it names more than 2 code roots, or it is cross-repo. Children are `<ID>.<n>`, producer first.
- Net-new work is sliced, never skipped: `.1` typed model plus validation and refusal tests, `.2` the one entry point that uses it, `.3`+ each further behavior.
- Cross-repo moves split into one child per repo: the destination copies the behavior first, then the source switches importers and deletes.

**Before every push**
- Work in a real `git worktree add` from `origin/main`. Never edit a shared checkout, never `git stash`, never `git add -A`, never force-push.
- Run the repo's own pre-commit on the changed files: `uvx --from pre-commit==4.6.0 pre-commit run --files $(git diff --name-only origin/main...HEAD)`. Fix every failure. No `noqa`, `type: ignore`, skip, xfail or whitelist entries to pass a gate.
- Run the targeted tests only, never a full suite.

**Landing**
- Every PR lands within minutes of going green; no PR sits idle. Mechanical conflicts (generated files, Markdown, `status.json`) are resolved automatically by the merge-train tool. Real conflicts are additive in most cases and are resolved, not deferred.
- Many open PRs land together as a merge train (one integration branch, one CI run), built with the orchestrator's merge-train tool.
- Full CI on main catches what the fast subset missed; regressions are fixed forward immediately.
- Landing in this repo: `gh pr merge --auto --merge` when the PR opens. The required checks are the fast PR subset. If the PR goes DIRTY, merge `origin/main` into it and push.

**Report**: at most 8 lines: PR URL, requirement IDs, test result, and any `ID:<main sha>` proof for rows already on main.

## What the SDK provides

- **Manifest model** (`agent_connector_sdk/manifest/`): the connector manifest
  schema, sync presets, tool-schema fingerprints, and loaders (`model.py`,
  `loader.py`, `presets.py`, `tool_schema.py`, `live_contract.py`).
- **Typed ports** (`agent_connector_sdk/ports/`): one protocol per extension
  boundary — `source_adapter` (extracts records from a source stream),
  `artifact_kind` (lists/validates/maps one kind of MCP-served content,
  including the `skill` kind in `agent_connector_sdk/artifacts/skills.py`),
  `transport` (opens sessions), `sink` (durably accepts batches and content
  packs), `writeback` (applies an EG-owned change set through an authorized
  source transport), and `repair_proposals`.
- **Reference adapters** (`agent_connector_sdk/adapters/`): the shipped
  `agent_connector_sdk.source_adapters` entry point (`mcp_tool`) and the event
  feed adapter.
- **Discovery and activation** (`agent_connector_sdk/discovery.py`): a
  connector extension self-registers as a Python entry point in one of four
  groups — `agent_connector_sdk.source_adapters`, `.artifact_kinds`,
  `.transports`, `.sinks` — declared under `[project.entry-points.*]` in its
  own `pyproject.toml`. `discover_extensions(group)` lists what is installed;
  `load_extension(group, name, policy=...)` loads it only when an
  `ActivationPolicy` (e.g. `CertifiedExtensions`) authorizes the exact
  `(group, name, distribution, version)` tuple — there is no permissive
  default. `connector-certify` (`agent_connector_sdk.certify.cli:main`) is the
  separate console script that compares a running connector's live tool
  fingerprints against its pinned manifest (`--check`) or writes new pins
  (`--write`).
- **Public surface contract** (`pyproject.toml`
  `[tool.agent_connector_sdk.wiring] public_modules`): the declared roots for
  this repository's own wiring gate. A module is reachable when it is in that
  list, is the target of a `[project.entry-points]` value, or is imported
  (directly or transitively) from a reachable module; every public name must
  also be exercised by a test under `tests/`.

## How to build a connector with it

1. Write the connector's manifest against `agent_connector_sdk.manifest.model`
   (`ConnectorManifest` and its nested specs).
2. Implement the typed port(s) the connector needs (`SourceAdapter`,
   `ArtifactKind`, `Transport`, `Sink`, `WriteBackPort`, ...) from
   `agent_connector_sdk/ports/`.
3. Register each implementation as an entry point in the connector's own
   `pyproject.toml`, under the matching `agent_connector_sdk.*` group, so
   `discover_extensions` finds it and an `ActivationPolicy` can certify it.
4. Prove conformance with the reusable suites in
   `agent_connector_sdk/testing/`: `source_adapters` (capability descriptor,
   pagination, checkpoint resume, idempotent re-run, malformed-input
   rejection, provenance completeness), `artifact_kinds` (listing, validation,
   deterministic digests, record mapping, malformed-entry rejection), and
   `writeback` (dry-run, optimistic conflict, authorization, idempotency,
   uncertain-outcome reconciliation) — assert with
   `agent_connector_sdk.testing.results.assert_conformant`.
5. Run `connector-certify PACKAGE --check -- COMMAND [ARG ...]` against the
   connector's own MCP server to confirm its live tool fingerprints match its
   pinned manifest before it is certified for activation.

## How to test it

`AGENTS.md` "Setup" and "Commands" are the source of truth; read them first.
In short:

1. Bootstrap once: `scripts/bootstrap.sh` (idempotent; add `--scanners` for
   the pinned native cccc, KISS, dupehound and jscpd scanners, which need
   cargo and npm). A Claude Code cloud session runs it through
   `.claude/hooks/session-start.sh`.
2. Tests: `uv run --frozen python -m pytest -q`.
3. Gates: `uvx --from pre-commit==4.6.0 pre-commit run --config
   .config/pre-commit.yaml --all-files`, then the same command with
   `--hook-stage pre-push` (tests, wheel build, secret history) and with
   `--hook-stage manual` (native scanners, privacy, fleet gates).

The wiring gates run inside the pre-commit stage as `check-orphan-modules` and
`check-public-api-tested` (`uv run --frozen python scripts/check_wiring.py
orphans|public-api`); the maintainer-only fleet gates `dependency-readiness`
and `phase-direction` (`bash scripts/run_fleet_gate.sh <gate>`) run at the
manual stage and print `SKIPPED (<gate>): <reason>` outside the fleet
workspace layout. While editing a public documentation surface, also run:

```bash
pre-commit try-repo ../pipelines public-surface --all-files
```

A hook whose prerequisite is missing prints `SKIPPED (<gate>): <reason>` and
exits 0 locally; with `CI` set it exits 2 (`CANNOT RUN`). Never bypass, baseline,
or suppress a failing gate — fix its cause.

## How to release it

Hosted CI is `.github/workflows/release.yml`: `gates` (the whole
`.config/pre-commit.yaml` suite, pre-commit then pre-push stage) must pass
before `build` (a byte-identical wheel built twice) runs; `scanner-quality`
(pinned cccc/KISS/dupehound/jscpd) is advisory; `publish-pypi` runs only on a
`v*` tag push, after `uv lock --check`.

This repository is a shared multi-worktree checkout:

- Create a real worktree before changing files —
  `git worktree add <path> -b <branch> main` — never harness-managed worktree
  isolation (`EnterWorktree`), which can alter shared Git configuration for
  every linked checkout.
- Never use `git stash`; its stack is shared by all worktrees.
- Never stage with `git add -A` or `git add .`; stage an explicit path
  allowlist, then inspect `git diff --cached`.
- Do not overwrite another lane's branch, generated files, lockfile, or
  uncommitted changes.
- **Do not use `--no-verify`.** Commit, push, tag, publish, and deploy are
  distinct operations and each needs its own completed gates and authority.
- Work on a topic branch, push it, and open a pull request against `main`
  (draft until gates pass); `gates` and `build` must be green before merge.
