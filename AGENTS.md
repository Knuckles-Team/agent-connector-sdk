# scion-sdk engineering contract

<!-- agent-contract:start -->
## Agent contract

Tool-neutral rules for any AI agent or human working in this repository. This block is maintained by the fleet standard; edit outside the markers.

- **Owner boundary:** this repository owns connector contracts, transports (including the MCP and A2A libraries), the engine client adapter and ontology pack generation (spec prefix `SDK-`). Feature routing across repositories: [ecosystem boundaries](https://github.com/Knuckles-Team/pipelines/blob/main/reference/ecosystem-boundaries.md).
- **Setup:** run `scripts/bootstrap.sh`. It is idempotent and non-interactive: it pins uv and Python, syncs the locked environment, installs the git hooks and prints the gate command.
- **Gates:** `uvx pre-commit run --all-files` must pass before you push. Do not bypass hooks to get green.
- **Commits:** one logical change per commit with a `Spec: <ID>` trailer (or `Spec: none (<reason>)`), plus a `Co-Authored-By:` trailer naming the assisting agent. Stage explicit paths only; never `git add -A` or `git add .`. Use your own configured Git identity, never a tool or bot name.
- **Org rules:** [organization AGENTS.md](https://github.com/Knuckles-Team/.github/blob/main/AGENTS.md).
<!-- agent-contract:end -->

## Spec-driven development

Every feature starts with a spec, in this order. Read `.specify/memory/constitution.md` first; it inherits the [organization constitution](https://github.com/Knuckles-Team/pipelines/blob/main/.specify/memory/constitution.md). Route the feature with the [ecosystem boundaries](https://github.com/Knuckles-Team/pipelines/blob/main/reference/ecosystem-boundaries.md) and file each part in its owner's `specs/`. Load the `scion-sdk-development` skill, which runs the flow. Rules: [spec standard](https://github.com/Knuckles-Team/pipelines/blob/main/reference/spec-standard.md); templates: pipelines `specs/_template/`.

| Step | Skill | Writes | Checked by |
|---|---|---|---|
| Constitution | `spec-generator` | `.specify/memory/constitution.md` | spec-standard constitution check |
| Specify | `spec-intake-wizard`, `spec-generator` | `specs/<id>/spec.md`, `requirements.md` | spec-standard |
| Clarify | `spec-generator` | resolves each `[NEEDS CLARIFICATION: ...]` marker | spec-standard clarification check |
| Plan | `spec-generator` | `plan.md` (upstream sections, Build contract, Production caller chain, Cross-repo seams) | spec-standard plan check |
| Tasks | `task-planner` | `tasks.md`: `- [ ] T001 [P] [US1] <ROW-ID> ...` | spec-standard task-line check |
| Analyze | `spec-verifier` | `checklists/requirements.md`, gap fixes | spec-standard analysis and checklist |
| Implement | `feature-development-pipeline` | code and bound tests (`mark.spec("ID")` or `// spec: ID`) | `pipelines-hook spec-trailers` |
| Land | repository development skill | commit with `Spec: <IDs>` directly above `Co-Authored-By` | `spec-status` computes SPECIFIED, LANDED, VERIFIED, RETIRED |
| Release | repository development skill | pipelines `releases/*.yml` bundles (PIPE-RELEASE-R020 to R024) | `release-standard` |

Never write code for a row that is not SPECIFIED in this repository's `specs/`. If no row owns the behavior, extend the owning spec first. Never write `status.json` or a `Status:` line; the state is computed.

This file defines the current repository architecture and the rules contributors
and automation must preserve. The public guides are built from [`docs/`](docs/)
and published through GitHub Pages.

## Boundaries

- **Owns:** connector contracts and transports. The transports are REST, GraphQL, gRPC, MCP, the A2A protocol library and the others. It also owns the EG client adapter and connector ontology pack generation.
- **Never builds:** serving or routing (route them to arbora). Facts, storage and pushdown planning go to epistemic-graph.
- **Allowed dependencies:** the epistemic-graph client and protocol libraries. It never imports `agent_utilities` or `arbora`. Connectors depend on this SDK only.

Route every feature with the [ecosystem boundaries standard](https://github.com/Knuckles-Team/pipelines/blob/main/reference/ecosystem-boundaries.md) before any code. A part this repository does not own goes to its owner's specs.

## What this repository owns

`scion-sdk` is the connector control and transport layer. It owns:

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
| `scion_sdk/mcp/` | server factory, auth composition, visibility, content, tools, subscriptions, registry leases |
| `scion_sdk/manifest/` | manifest models, loaders, sync presets, live-contract validation, fingerprints |
| `scion_sdk/ports/` | one typed protocol per extension boundary |
| `scion_sdk/discovery.py` | entry-point discovery and explicit activation policy |
| `scion_sdk/adapters/` | reference source adapters |
| `scion_sdk/artifacts/` | MCP content capture and canonical pack construction |
| `scion_sdk/transports/` | authenticated connector sessions |
| `scion_sdk/sinks/` | graph-bound sink adapters and readiness reporting |
| `scion_sdk/repository/` | authenticated immutable snapshot paging, manifests, and bounded transport to EG IndexRepository; no semantic writer |
| `scion_sdk/runner/` | `connector-sync` composition, workers, scheduling, durable EG status reads, health |
| `scion_sdk/writeback/` | governed dry-run, authorization, version checks, idempotency, reconciliation |
| `scion_sdk/http/`, `tls/`, `auth/` | governed outbound requests and identity boundaries |
| `scion_sdk/credentials/` | `env://` and `openbao://` references and resolvers |
| `scion_sdk/testing/` | reusable connector conformance suites |
| `tests/` | unit, integration, contract, and gate tests |
| `docs/` | public GitHub Pages sources and generated shared-theme assets |
| `.config/mkdocs-overrides/` | shared MkDocs Material template overrides |

The public Python surface is declared in
`pyproject.toml` under `[tool.scion_sdk.wiring]`. Every module must be
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
[GitHub Pages site](https://knuckles-team.github.io/scion-sdk/) contains
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
  before merge; scanners report weekly in `advisory.yml`.

## Specs: extend first

Find the spec row that owns the behavior before any code change. Search with `git grep -n "<term>" -- specs`. Cite the row ID in the commit `Spec:` trailer. Extend the owning spec before any new spec text. Add a child row, a new rollup, or a dated `plan.md` "Amendments" entry. Create a new spec only for a capability that no spec owns. Audits, reviews, and carry-overs land in the owning spec. They never get a spec directory. Reuse an existing function, module, or store before adding one. The rules are the ecosystem [spec standard](https://github.com/Knuckles-Team/pipelines/blob/main/reference/spec-standard.md).
