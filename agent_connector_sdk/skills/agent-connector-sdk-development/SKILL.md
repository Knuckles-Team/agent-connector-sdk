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

## Step 0: route the feature

Route the feature before any code.

1. Read the [ecosystem boundaries standard](https://github.com/Knuckles-Team/pipelines/blob/main/reference/ecosystem-boundaries.md).
2. Split the feature into parts with its routing procedure.
3. If a part is not owned by agent-connector-sdk, stop work on that part. Write its row in the owner's `specs/`, then link it by ID.
4. Continue here only with the parts that agent-connector-sdk owns.

## Rapid delivery: the 5-minute contract

Specs are already designed. The work is implementation, delivered in very small, continuously landed slices.

**Extend first (anti-sprawl)**
- Before any code change, find the spec row that owns the behavior: `git grep -n "<term>" -- specs`. Cite its ID in the commit `Spec:` trailer.
- Before any new spec text, extend the owning spec: a child row (`R012.4`), a new rollup at the end of that spec, or a dated entry in the `plan.md` section "Amendments". Create a new spec only for a capability that no spec owns, and record the search in "Why a new spec".
- Audits, reviews, gap analyses and carry-overs never get a spec directory. Their findings land in the spec that owns the row; a finding against another repository lands in that repository's spec.
- Before any new function, module, planner, selector or store, search for the existing one and reuse it. A second implementation of an owned capability is a defect, not a delivery.
- The rules are in `specs/README.md`. The `spec-standard` gate enforces the names, file set, title and index.

**Time and size**
- One agent delivers one PR in 5 minutes or less. No agent or sub-agent runs longer than 5 minutes; an orchestrator dispatches the next slice to a fresh agent.
- Self-timer (hard): run `date +%s > /tmp/agent-start-$$` as your FIRST command, and before every later step check elapsed with `echo $(( $(date +%s) - $(cat /tmp/agent-start-*) ))`. At 300 s, stop starting new work. At 480 s, commit what passes, push it, open the PR, report and STOP. Never exceed 600 s. Never wait on CI or background jobs; use `git commit --no-verify` and `git push --no-verify` after running pre-commit on the changed files yourself.
- CI turns around in 5 minutes or less. PR CI runs the fast subset: lint, type check, the spec check, and only the tests and crates the diff touches. Pushes to main run the full suite.
- CI timer (hard): every PR-path job carries `timeout-minutes: ${{ github.event_name == 'pull_request' && 10 || 60 }}`, so a PR gate is killed at 10 minutes and a slow gate shows up as a failure instead of a silent queue.
- Never spawn sub-agents from a delivery agent.

**Investigation budget**
- At most 2 minutes and about 10 tool calls of reading before the first edit, and at most about 25 tool calls per PR.
- If the change is not clear by then, ship the `.1` slice (typed model plus refusal test) or skip the row with a one-line note. Do not write deferral essays.
- Trust the orchestrator's evidence and ID list; do not re-verify it.

**Sizing (deterministic)**
- Split a requirement when its size score is above 6, it names more than 2 code roots, or it is cross-repo. Children are `<ID>.<n>`, producer first.
- Net-new work is sliced, never skipped: `.1` typed model plus validation and refusal tests, `.2` the one entry point that uses it, `.3`+ each further behavior.
- Cross-repo moves split into one child per repo: the destination copies the behavior first, then the source switches importers and deletes.

**Specs update themselves (land VERIFIED, not just LANDED)**
- Every commit that delivers a requirement ends with the trailer `Spec: <ID>[, <ID>...]`. A commit that touches code without delivering one says `Spec: none (ci|deps|refactor|fix-forward)`.
- Every delivered ID gets at least one test bound to it in the same PR. Python: `@pytest.mark.spec("<ID>")`. Rust/TypeScript: a `// spec: <ID>` line directly above the test.
- Never hand-edit `status.json`; it is generated (`spec-status`). Never write placeholder SHAs. If the work is only part of a requirement, decompose it into `<ID>.<n>` children first and deliver whole children.
- Write the marker with the literal ID, never a variable. Put `Spec:` and `Co-Authored-By:` on consecutive lines in the last paragraph of the commit message, or `Spec:` is not read as a trailer.
- Generated status depends on the commit: run `pipelines-hook spec-status --write` again after committing and commit the result.
- The generator applies the rules. Run `pipelines-hook spec-status` to see each row's state.

**Delivered means the row's acceptance is met**
- Never delete or stub out behaviour whose replacement is not wired. Never make a caller "fail closed" in place of repointing it. Never substitute a scope, weaken an assertion or add an allowlist entry to pass a gate.
- If the replacement lives in another repository, do not deliver: record the blocker in the row, name the missing capability, and stop. The orchestrator adds the row in the owning repository.
- Never re-add a path that another requirement retired; report the conflict.
- Valid outcomes are DELIVERED (with a bound test), SPLIT, BLOCKED and GAP (a "landed" row that is not really delivered). A half-delivery is not an outcome.

**Where progress shows**
- The repository's spec-delivery page is rebuilt from `specs/*/status.json` on each push to main. SPECIFIED is written, LANDED is on main, VERIFIED is on main with a bound test.

**Before every push**
- Work in a real `git worktree add` from `origin/main`. Never edit a shared checkout, never `git stash`, never `git add -A`, never force-push.
- Run the repo's own pre-commit on the changed files: `uvx --from pre-commit==4.6.0 pre-commit run --files $(git diff --name-only origin/main...HEAD)`. Fix every failure. No `noqa`, `type: ignore`, skip, xfail or whitelist entries to pass a gate.
- Run the targeted tests only, never a full suite. Run the type checker on every changed file, and keep each function at cyclomatic complexity 10 or less.

**Landing**
- Every PR lands within minutes of going green; no PR sits idle. Mechanical conflicts (generated files, Markdown, `status.json`) are resolved automatically by the merge-train tool. Real conflicts are additive in most cases and are resolved, not deferred.
- Many open PRs land together as a merge train: one integration branch and one CI run.
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
  separate console script that checks a running connector's declared sync tools
  against their live definitions.
- **Public surface contract** (`pyproject.toml`
  `[tool.agent_connector_sdk.wiring] public_modules`): the declared roots for
  this repository's own wiring gate. A module is reachable when it is in that
  list, is the target of a `[project.entry-points]` value, or is imported
  (directly or transitively) from a reachable module; every public name must
  also be exercised by a test under `tests/`.

## How to build a connector with it

1. Declare each ingestible source with `source_meta(...)` on its read tool
   (`agent_connector_sdk.ingest.live_declaration`); the server serves them at
   `connector://resources`.
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
5. Run `connector-certify -- COMMAND [ARG ...]` against the connector's own MCP
   server to confirm its declared sync tools are valid before it is certified
   for activation.

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

Release procedure (bump first, tag last; X.Y.Z is the intended version):

1. Bump on a topic branch: set `version` in `pyproject.toml` and
   `current_version` in `.bumpversion.cfg` to X.Y.Z (`bump2version` also edits
   `pyproject.toml`; run it with `--no-commit --no-tag`). Refresh `uv.lock`
   (`uv lock`) and the recorded fixtures that embed the version,
   `tests/fixtures/pinned_import_graph.txt` and
   `tests/fixtures/pinned_import_graph.provenance.json`
   (`grep -rn '<old version>' tests/fixtures uv.lock`).
2. Merge the bump PR to `main` (rebase merge, `gates` and `build` green).
3. Read back the merged commit before tagging:
   `git show <commit>:pyproject.toml | grep ^version` prints `version = "X.Y.Z"`,
   `git show <commit>:.bumpversion.cfg | grep current_version` prints X.Y.Z, and
   `curl -s -o /dev/null -w '%{http_code}' https://pypi.org/pypi/agent-connector-sdk/X.Y.Z/json`
   prints `404`.
4. Only then tag that exact commit: `git tag vX.Y.Z <commit> && git push origin vX.Y.Z`.
5. Confirm both the wheel and the sdist (`release.yml` uploads
   `dist/*.whl dist/*.tar.gz`) appear at
   `https://pypi.org/pypi/agent-connector-sdk/X.Y.Z/json` (`urls`).
6. A tag on the wrong commit with nothing published: delete it
   (`git push origin :refs/tags/vX.Y.Z`, `git tag -d vX.Y.Z`) and re-tag the
   right commit. If anything was published, never reuse the version: cut the
   next patch from step 1.

The tag must equal the package version: a tag whose `pyproject.toml` is older
rebuilds the old version and PyPI refuses it (v0.5.1 on a 0.5.0 commit, twice).
This workflow does not yet run the shared early guard; wiring it needs
`uses: Knuckles-Team/pipelines/.github/actions/verify-release-version@<sha>`
once the pipelines guard is merged.

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
