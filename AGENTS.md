# AGENTS.md

Guide for agents and humans working in **agent-connector-sdk**, the connector SDK of
the agent-packages fleet (RF-ADR-009, workspace phase 3). Published documentation
is the GitHub Pages site built from `pages/`.

## What this repository owns

| Owns | Must not own |
|---|---|
| MCP server scaffolding (server factory, authentication, visibility, tool surface, action dispatch, concurrency) | agents, orchestration, LLM calls |
| Connector manifest schema and validator, sync presets, tool-schema fingerprints | knowledge-graph logic, ontology reasoning, storage |
| Serving connector content (skills, prompts, ontologies, shapes, manifest) as MCP primitives | the pack or record schema (epistemic-graph owns it) |
| Extension ports (`SourceAdapter`, `ArtifactKind`, `Transport`, `Sink`), entry-point discovery, the conformance kit | vendor API clients (connectors own them) |

Dependencies are `fastmcp`, the `epistemic_graph` client, `pydantic`, `PyYAML`,
`httpx` and `anyio`. **Never add agent-utilities or any later-phase package**; the
phase-direction hook fails the push.

## Layout

| Path | Contents |
|---|---|
| `agent_connector_sdk/config.py`, `utilities.py`, `exceptions.py`, `identity.py` | configuration, coercion, exceptions, actor context |
| `agent_connector_sdk/credentials/` | `env://` and `openbao://` references and resolvers |
| `agent_connector_sdk/contracts.py` | the epistemic-graph seam types (replaced by contract-generated types after W1) |
| `agent_connector_sdk/ports/` | one protocol per module, plus errors |
| `agent_connector_sdk/discovery.py` | entry-point groups and the activation policy |
| `agent_connector_sdk/manifest/` | manifest model, presets, fingerprints, live-contract validation, loaders |
| `agent_connector_sdk/mcp/` | server factory and everything it composes |
| `agent_connector_sdk/runner/` | the `connector-sync` scheduler: registry, workers, backoff, checkpoints, and its health surface (`health_state.py`, `health_server.py` -- see [Connector sync](pages/connector-sync.md)) |
| `agent_connector_sdk/adapters/`, `artifacts/`, `transports/`, `sinks/` | reference implementations registered as entry points |
| `agent_connector_sdk/testing/` | the conformance kit |
| `tests/` | the suite; `fixture_server.py` and `fixture_package/` are an in-process connector |
| `scripts/` | `check_wiring.py`, the SDK's own wiring gates (orphan modules, tested public API); every other gate is a shared hook |
| `pages/` | hand-written Pages sources (`mkdocs.yml` sets `docs_dir: pages`) |

`pyproject.toml` `[tool.agent_connector_sdk.wiring] public_modules` is the public
surface. A new module is either imported by a reachable module or added there,
and then its public names need tests.

## Commands

```bash
uv sync                                   # the project environment (Python 3.12)
uv run --frozen python -m pytest -q       # tests
pre-commit run --all-files                # commit-stage suite
pre-commit run --all-files --hook-stage pre-push   # push-stage suite
pre-commit run complexity-census --hook-stage manual --all-files   # absolute cccc census
pre-commit run kiss-census --hook-stage manual --all-files         # absolute KISS census
```

## Rules

- **Worktrees, not the shared checkout.** Work in
  `git worktree add <path> -b <branch> main`. Never use the harness's
  `EnterWorktree` or `isolation: "worktree"` against this repository, and never
  `git stash` (the stash is shared by every worktree).
- **Stage explicit paths.** Never `git add -A` or `git add .`; review
  `git diff --cached` before committing.
- **Full green, no suppressions.** No `noqa`, `type: ignore`, skips, xfails,
  baselines or ratchets. No `--no-verify`.
- **Shape limits.** New code meets cccc (cyclomatic 10, cognitive 15) and
  `.kiss/kiss.toml` (for example at most 10 functions per file, 300 lines per file,
  20 calls and 5 returns per function, 3 positional arguments, one protocol per
  module). The census holds the package at zero.
- **Fail closed.** Unknown auth modes, unverified tool contracts, malformed
  records, uncertified extensions and credential values in configuration all
  raise; nothing degrades to permissive.
- **No version suffixes** in names (`StorageKernel`, not `StorageKernelV1`) and
  no compatibility shims.
- **The one declared stub.** `sinks/epistemic_graph.py` raises
  `NotImplementedError` for pack import and record ingestion until epistemic-graph
  publishes those methods (RF-ADR-009 W1). The stub gates accept exactly those two
  raises and print them as NOT DONE. Nothing that depends on them counts as done.

## Quality gates

The suite adopts agent-utilities' tool hooks and consumes every repository-agnostic
gate from the shared hook repository **Knuckles-Team/pipelines**
(`.pre-commit-hooks.yaml`, pinned to a full commit SHA in `.pre-commit-config.yaml`):
complexity (cccc) and KISS, staged and census; dupehound and jscpd; secret history,
security sanitizer, tracked privacy, dependency audit and supply chain; root
hygiene, gitignore convergence, sprawl, Mermaid and pre-commit patch safety;
no-stub, stubs, swallowed errors, event-loop blocking, import cycles, env sprawl
and stdout writes; and the CI gate replica. No gate script is copied into this
repository and none is exempt from any gate. The scanner versions are pinned by
the hook repository: cccc 1.6.0, kiss 0.4.10, dupehound 0.1.2, jscpd 5.0.16.

Repository-specific inputs live in `pyproject.toml` `[tool.pipelines_hooks]`:
`packages`, `env_sprawl.allow_files` (`config.py` is the only environment reader),
`stdout_writes.served_paths` (the whole package is served MCP surface),
`stubs.declared_seams` (the one declared stub above), and the `ci_replica` workflow
registry. `.repo-layout.toml` declares every root entry, dot-files in `[dotfiles]`.
CI runs the same pinned hooks with `pre-commit run <hook> --hook-stage manual`.

Until a new pipelines revision is pushed, a machine resolves it only from a local
clone: run pre-commit with `GIT_CONFIG_COUNT=1`,
`GIT_CONFIG_KEY_0=url.<local pipelines checkout>.insteadOf` and
`GIT_CONFIG_VALUE_0=https://github.com/Knuckles-Team/pipelines` in the environment
(no git configuration is changed).

Hooks from agent-utilities that were **not** adopted, and why:

| Hook(s) | Reason |
|---|---|
| lane-guard, check-concept-gaps, check-concept-governance(-merged), guardrail-concept-freshness, guardrail-concept-domain-vocab | agent-utilities' concept registry and merge-queue lanes |
| turtle-format, check-ontology, check-identifier-interpolation | the SDK owns no ontology and builds no graph queries; epistemic-graph validates ontologies |
| check-release-catalogs, check-skill-name-collision, guardrail-kg-skill-coverage, guardrail-prebundled-skills, guardrail-prompt-schema | agent-utilities' connector catalog and bundled skills |
| guardrail-genesis-manifest, guardrail-surface-parity, guardrail-openapi-coverage, guardrail-cpd-drift, guardrail-docs-contract, docs-consistency | agent-utilities' gateway, genesis and `/docs` contracts (this repository has no `/docs`) |
| guardrail-epistemic-operations-protocol, guardrail-no-pyo3, guardrail-retrieval-quality, guardrail-eval-corpus, guardrail-reliability-corpus, guardrail-citation-lineage, guardrail-liveness, guardrail-prod-profile, guardrail-entrypoint-engine-authority, backend-interface-parity, backend-parity, constrained-parallelism | agent-utilities' engine, retrieval, evaluation and backend internals |
| guardrail-version-consistency, check-wire-first | replaced by `check-bumpversion`, a version test, and `check-orphan-modules` / `check-public-api-tested` (`scripts/check_wiring.py`, no baseline file) |
| guardrail-removed-symbol-consumers | compares against a published `main` and a fleet consumer index; adopt once the SDK has a release consumers import |
| check-import-safety | its Windows shim cannot model third-party guarded imports without an exclusion list; the package targets POSIX |
| check-http-transport-closure | agent-utilities' governed HTTP transport layer |
| env-var-drift | lives in agent-utilities; it moves to the SDK with the connector switch (W3) |
| check-agent-standards, check-cli-help, hadolint, docker-compose-check, nbqa-ruff | no `agent_server.py`/`mcp_server.py`, Dockerfiles, compose files or notebooks here |
| contract-checks, check-current-only-contract-debt, check-security-*, check-guardrails-release-supply-chain, guardrail-gate-meta-tests, guardrail-coupling-advisory, guardrail-parity | agent-utilities' own security corpus and test suites; this repository's gate tests live in `tests/gates` and run with pytest |
