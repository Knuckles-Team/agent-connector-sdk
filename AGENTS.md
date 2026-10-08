# agent-connector-sdk engineering contract

This file defines the current repository architecture and the rules contributors
and automation must preserve. The public guides are built from [`docs/`](docs/)
and published through GitHub Pages.

## What this repository owns

`agent-connector-sdk` is the connector control and transport layer. It owns:

- secure FastMCP server construction, authentication, network-exposure checks,
  visibility, rate limiting, action dispatch, and tool registration;
- connector manifests, sync presets, tool-schema fingerprints, and content
  publication for skills, prompts, ontologies, SHACL shapes, and manifests;
- typed extension ports for sources, artifacts, transports, sinks, registries,
  authorization, and write-back;
- connector discovery, certification, conformance checks, source scheduling,
  health reporting, retries, and progress;
- governed HTTP, TLS, credential-reference, pagination, and error handling.

The repository does not own vendor API implementations, durable graph storage,
ontology reasoning, agents, model calls, workflow orchestration, or deployment
policy. Connectors own vendor-specific transport. `epistemic-graph` owns durable
records, graph schemas, validation, reasoning, receipts, and semantic indexing.
The agent control plane owns goals, workflows, and routing.

`agent-utilities` is not a dependency. Keep dependency direction enforceable by
the `phase-direction` gate.

## Architecture and module map

| Path | Responsibility |
|---|---|
| `agent_connector_sdk/mcp/` | server factory, auth composition, visibility, content, tools, subscriptions, registry leases |
| `agent_connector_sdk/manifest/` | manifest models, loaders, sync presets, live-contract validation, fingerprints |
| `agent_connector_sdk/ports/` | one typed protocol per extension boundary |
| `agent_connector_sdk/discovery.py` | entry-point discovery and explicit activation policy |
| `agent_connector_sdk/adapters/` | reference source adapters |
| `agent_connector_sdk/artifacts/` | MCP content capture and canonical pack construction |
| `agent_connector_sdk/transports/` | authenticated connector sessions |
| `agent_connector_sdk/sinks/` | graph-bound sink adapters and readiness reporting |
| `agent_connector_sdk/repository/` | authenticated immutable snapshot paging, manifests, and bounded transport to EG IndexRepository; no semantic writer |
| `agent_connector_sdk/runner/` | `connector-sync` composition, workers, scheduling, durable EG status reads, health |
| `agent_connector_sdk/writeback/` | governed dry-run, authorization, version checks, idempotency, reconciliation |
| `agent_connector_sdk/http/`, `tls/`, `auth/` | governed outbound requests and identity boundaries |
| `agent_connector_sdk/credentials/` | `env://` and `openbao://` references and resolvers |
| `agent_connector_sdk/testing/` | reusable connector conformance suites |
| `tests/` | unit, integration, contract, and gate tests |
| `docs/` | public GitHub Pages sources and generated shared-theme assets |
| `.config/mkdocs-overrides/` | shared MkDocs Material template overrides |

The public Python surface is declared in
`pyproject.toml` under `[tool.agent_connector_sdk.wiring]`. Every module must be
reachable from a public module or an entry point, and every public name must be
exercised by a test.

The runner activates an extension only after its exact group, name,
distribution, and version are certified. Sink readiness is capability based.
The bundled epistemic-graph sink reads durable SourceIngest status and commits
through generated SourceIngest, ConnectorPack, and WriteBack contracts; it does
not retain a parallel cursor authority. Construction requires a checked
generated client and live ConnectorPack authority resolver.

## Setup

From a fresh clone (locally, or in a Claude Code cloud session where
`.claude/hooks/session-start.sh` runs it automatically):

```bash
scripts/bootstrap.sh              # uv >= 0.9, pinned Python, EG contract, locked env, git hooks
scripts/bootstrap.sh --scanners   # also the pinned cccc/KISS/dupehound/jscpd (needs cargo + npm)
```

`scripts/bootstrap.sh` is idempotent. `scripts/install_scanners.sh` is the only
place the native scanner pins live; hosted CI calls it too and keys its cache on
the script's hash.

## Commands

```bash
uv run --frozen python -m pytest -q
uvx --from pre-commit==4.6.0 pre-commit run --config .config/pre-commit.yaml --all-files
uvx --from pre-commit==4.6.0 pre-commit run --config .config/pre-commit.yaml --all-files --hook-stage pre-push
uvx --from pre-commit==4.6.0 pre-commit run --config .config/pre-commit.yaml --all-files --hook-stage manual
```

Hosted CI (`.github/workflows/release.yml`) runs the same configuration: the
whole pre-commit stage, then the pre-push stage (tests, wheel build, secret
history). Run the shared documentation contract directly while editing public
surfaces:

```bash
pre-commit try-repo ../pipelines public-surface --all-files
```

## Quality gates

The repository consumes shared, pinned hooks from
[`Knuckles-Team/pipelines`](https://github.com/Knuckles-Team/pipelines) and keeps
repository-specific settings in `[tool.pipelines_hooks]`.

- **Public surface:** README badges, headings, Pages links, local links, document
  size, current-state language, and the required `AGENTS.md` structure.
- **Code shape:** cccc, KISS, dupehound, jscpd, import cycles, swallowed errors,
  event-loop blocking, environment reads, stdout purity, and production seams.
- **Security and supply chain:** secret history, tracked privacy, immutable
  sources, security sanitation, and repository hygiene. No gate calls an
  external service such as a vulnerability database.
- **Correctness:** pytest, strict mypy, Ruff, Bandit, Vulture, codespell, wiring,
  dependency readiness, and dependency direction.
- **Delivery:** strict MkDocs, reproducible wheel build, and version
  consistency. The hosted Pages workflow
  provisions the shared theme before its strict MkDocs build; release checks
  validate the lockfile.

Native scanners must match the versions required by the pinned hook revision.
Gates check behaviour or structure, never hand-kept counts or copied pins, so an
unrelated change never needs a gate edit. The pre-commit and pre-push stages run
from a fresh clone after `scripts/bootstrap.sh`. Gates that need more than that
(native scanners, the operator privacy catalog, the fleet workspace checkout)
are in the manual stage: the repository's fleet gates print
`SKIPPED (<gate>): <reason>` and exit 0 locally and fail closed with
`CANNOT RUN` (exit 2) when `CI` is set; a shared scanner hook reports a missing
or drifted binary as `CANNOT RUN`. Do not weaken, suppress, baseline, or bypass
a gate to land a change.

## Development rules

- Put shared connector behavior in this SDK and vendor behavior in the owning
  connector. Do not add graph storage, reasoning, agents, or orchestration here.
- Preserve one contract at every boundary. Import epistemic-graph-owned schemas
  from its generated client surface; do not duplicate wire DTOs or digests.
- Fail closed for unknown auth, unsafe exposure, malformed records, unverified
  tool contracts, uncertified extensions, literal credentials, and uncertain
  write-back effects.
- Keep secrets as references. Never serialize resolved values into configuration,
  logs, errors, reports, fixtures, or manifests.
- Keep async paths non-blocking and place bounded blocking work behind the
  established thread boundary.
- Use current names without version suffixes, compatibility aliases, or parallel
  implementations.
- Add focused positive and adversarial tests for each invariant. Check discovery
  as well as direct construction for entry-point features.
- Keep public examples synthetic and portable. Do not publish machine paths,
  private endpoints, credentials, internal plans, or implementation history.
- Stage only reviewed paths and run every affected gate before committing.

## Documentation

[`README.md`](README.md) is the concise project entry point. The
[GitHub Pages site](https://knuckles-team.github.io/agent-connector-sdk/) contains
the operational and API guides. Keep README, Pages, code, tests, entry points,
and CLI help synchronized in the same change.

Public documentation describes the architecture and capabilities that exist in
the referenced commit. Design discussions, rollout sequencing, and program
tracking belong outside the public repository surface.

The hosted Pages workflow runs `mkdocs build --strict` after provisioning the
shared theme. A local strict build needs that same theme checkout. Add a page
to `mkdocs.yml` navigation when it is part of the supported public contract,
and keep every local Markdown link repository-relative and valid.

## Branching & isolation

This repository is a shared multi-worktree checkout.

- Create a real worktree with
  `git worktree add <path> -b <branch> main` before changing files.
- Never use harness-managed worktree isolation or `EnterWorktree`; it can alter
  shared Git configuration for every linked checkout.
- Never use `git stash`; its stack is shared by all worktrees.
- Never stage with `git add -A` or `git add .`. Stage an explicit path allowlist,
  inspect `git diff --cached`, and keep unrelated work untouched.
- Do not overwrite another lane's branch, generated files, lockfile, or
  uncommitted changes. Rebase or recompose only after identifying ownership.
- Do not use `--no-verify`. Commit, push, tag, publish, and deploy are distinct
  operations and each requires its own completed gates and authority.
- Work on a topic branch, push it, and open a pull request against `main`
  (draft until the gates pass). The `gates` and `build` jobs must be green
  before merge; `scanner-quality` is advisory.
