# SCION-QUALITY-RELEASE — Portable SDK quality, Pages, and release

**Requirement IDs:** SCION-QUALITY-RELEASE-R001, SCION-QUALITY-RELEASE-R002, SCION-QUALITY-RELEASE-R003, SCION-QUALITY-RELEASE-R004, SCION-QUALITY-RELEASE-R005.
**Owner:** scion-sdk. **Delivery state:** UNKNOWN. **Acceptance state:** OPEN.

## Outcome

An external contributor validates code and public docs from a fresh checkout with no running platform. The release job builds the SDK wheel against a compatible published graph-client wheel. It publishes guides through GitHub Pages. A checked-in `/docs` deployment copy is not required. Source docs may stay until one maintained Pages source replaces them. The source of truth is explicit, and generated output does not block unrelated code pull requests.

## Gate architecture

Separate two evidence classes. **Pull-request gates** use declared, lockable tools and synthetic fixtures: unit and contract pytest, Ruff, mypy, CCCC, KISS, Dupehound, jscpd, package wiring, dependency direction, public-doc link/privacy scan, build metadata, and wheel import smoke. They must have deterministic startup and no mandatory private socket, secret store, provider account, paid entitlement, external graph, registry publication, or protected branch permission. Missing required local tooling is provisioned from the repo lock or recorded as an infrastructure failure; it is never silently skipped.

**Release/acceptance gates** may use a contributor-owned environment: real graph client and connector receipts, strict Pages build/publication, online vulnerability audit, and artifact publication. These report `PASS`, `FAIL`, or `NOT RUN` separately from pull-request source status. A live acceptance failure blocks acceptance/release, not review of source changes. The release job must verify published wheel digest, installed consumer import and generated DTO compatibility; a local source overlay cannot pass it.

Public-doc privacy scanning searches Markdown, HTML source, examples and generated Pages inputs for private address ranges, host aliases, environment-only domains, credential strings, and machine paths. Test the scanner with planted violations to prove a red result. Synthetic RFC 5737/3849 addresses and `example.com` are allowed fixtures. Keep links relative or public. Pages navigation and SDK API docs must describe the exact released source, not a future design as current behavior.

## Fresh-checkout workflow

Install Python and `uv` as pinned in `pyproject.toml`; run `uv sync`, `uv run --frozen python -m pytest -q`, lint/type/wiring hooks, and `python -m build` or the repository's pinned wheel command (SCION-QUALITY-RELEASE-R003). The build must execute under that pinned interpreter rather than falling back to the hosting runner's system Python. The Pages source build runs in CI with its declared theme dependency. Contributors may run it locally using the same lock, and the resulting dependency import graph must reproduce the hosted continuous-integration run's recorded result exactly (SCION-QUALITY-RELEASE-R005); source PR validation never assumes a pre-existing sibling checkout.

The public README follows a fixed section order leading with a one-file connector quick start, and the published documentation site presents a task-first tutorial and architecture guide rather than an API-reference-first structure (SCION-QUALITY-RELEASE-R004).

For R005, the SDK installs `medulla` from PyPI only, never from source. `uv.lock` pins its registry wheels by SHA-256 and has no source distribution. `[tool.uv] no-build-package` forbids a source build, so the toolchain never compiles native code. `scripts/epistemic_graph_release.json` names one locked wheel; the build job uses it for the consumer check. Bootstrap runs `uv sync --frozen`, then proves that the generated contracts import from the installed wheel. Graph inspection compares installed metadata with the lock. Every SDK-consumed Python contract module must resolve inside the installed wheel package. Include EG and each active transitive dependency in the graph. Traverse requested extras and fail closed on source, wheel, origin, metadata, dependency, or graph mismatch.

## Evidence and completion

| Gate | State | Evidence |
|---|---|---|
| Portable cloud PR gate | OPEN | Pending exact CI run |
| Planted privacy scanner violations | OPEN | Pending focused test |
| Published Pages and wheel consumer | OPEN | Pending URLs, artifact digest and release run |

The **LANDED** state requires the exact merge and docs source. The **ACCEPTED** state requires passing cloud PR tests from a fresh checkout and independent release evidence. A stale gate does not waive source correctness checks.

Requirement IDs are defined in [requirements.md](requirements.md); delivery state per ID is in `status.json`.
