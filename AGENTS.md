# agent-connector-sdk engineering contract

This file defines the current repository architecture and the rules contributors
and automation must preserve. The public guides are built from [`pages/`](pages/)
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
| `agent_connector_sdk/runner/` | `connector-sync` composition, workers, scheduling, durable EG status reads, health |
| `agent_connector_sdk/writeback/` | governed dry-run, authorization, version checks, idempotency, reconciliation |
| `agent_connector_sdk/http/`, `tls/`, `auth/` | governed outbound requests and identity boundaries |
| `agent_connector_sdk/credentials/` | `env://` and `openbao://` references and resolvers |
| `agent_connector_sdk/testing/` | reusable connector conformance suites |
| `tests/` | unit, integration, contract, and gate tests |
| `pages/` | public GitHub Pages sources |

The public Python surface is declared in
`pyproject.toml` under `[tool.agent_connector_sdk.wiring]`. Every module must be
reachable from a public module or an entry point, and every public name must be
exercised by a test.

The runner activates an extension only after its exact group, name,
distribution, and version are certified. Sink readiness is capability based. A
sink that cannot commit returns `ready=False`; the runner fails readiness and
does not submit source data. The bundled epistemic-graph sink reads the durable
SourceIngest status and commits through generated SourceIngest, ConnectorPack,
and WriteBack contracts; it does not retain a parallel cursor authority.

## Commands

```bash
uv sync
uv run --frozen python -m pytest -q
uv run --frozen --with mypy==1.20.2 \
  --with types-PyYAML==6.0.12.20260518 \
  python -m mypy agent_connector_sdk
uvx --from ruff==0.16.0 ruff check agent_connector_sdk tests
uvx --from ruff==0.16.0 ruff format --check agent_connector_sdk tests
uv run --frozen --only-group docs mkdocs build --strict
python scripts/check_wiring.py orphans
python scripts/check_wiring.py public-api
pre-commit run --config .config/pre-commit.yaml --all-files
pre-commit run --config .config/pre-commit.yaml --all-files --hook-stage pre-push
```

Run the shared documentation contract directly while editing public surfaces:

```bash
pre-commit try-repo --config .config/pre-commit.yaml ../pipelines public-surface --all-files
```

## Quality gates

The repository consumes shared, pinned hooks from
[`Knuckles-Team/pipelines`](https://github.com/Knuckles-Team/pipelines) and keeps
repository-specific settings in `[tool.pipelines_hooks]`.

- **Public surface:** README badges, headings, Pages links, local links, document
  size, current-state language, and the required `AGENTS.md` structure.
- **Code shape:** cccc, KISS, dupehound, jscpd, import cycles, swallowed errors,
  event-loop blocking, environment reads, stdout purity, and production seams.
- **Security and supply chain:** secret history, tracked privacy, dependency
  audit, immutable sources, security sanitation, and repository hygiene.
- **Correctness:** pytest, strict mypy, Ruff, Bandit, Vulture, codespell, wiring,
  dependency readiness, and dependency direction.
- **Delivery:** strict MkDocs, reproducible wheel build, version consistency,
  and the local CI replica. These full checks run manually or in hosted CI; the
  automatic pre-push stage remains bounded.

Native scanners must match the versions required by the pinned hook revision.
A missing scanner, configuration, dependency, or privacy catalog is a gate
failure, never a skipped success. Do not weaken, suppress, baseline, or bypass a
gate to land a change.

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
- Add focused positive and adversarial tests for each invariant. Verify discovery
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

Build Pages with `mkdocs build --strict`. Add a page to `mkdocs.yml` navigation
when it is part of the supported public contract, and keep every local Markdown
link repository-relative and valid.

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
