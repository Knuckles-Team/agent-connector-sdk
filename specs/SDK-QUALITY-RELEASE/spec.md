# Portable SDK quality, Pages, and release

**Program IDs:** EH-212, EH-369, SDK final release lane, SDK public docs lane.
**Owner:** agent-connector-sdk. **Delivery state:** UNKNOWN. **Acceptance state:** OPEN.

## Outcome

An external contributor can validate code and public documentation from a fresh checkout without access to a running platform. The release pipeline then builds an installed SDK wheel against a published compatible graph-client wheel and publishes public guides through GitHub Pages. No stale checked-in `/docs` deployment copy is a quality prerequisite. Source docs needed to build Pages may remain in the repository until replaced by a single maintained Pages source; the source of truth must be explicit and generated outputs must not block unrelated code pull requests.

## Gate architecture

Separate two evidence classes. **Pull-request gates** use declared, lockable tools and synthetic fixtures: unit and contract pytest, Ruff, mypy, CCCC, KISS, Dupehound, jscpd, package wiring, dependency direction, public-doc link/privacy scan, build metadata, and wheel import smoke. They must have deterministic startup and no mandatory private socket, secret store, provider account, paid entitlement, external graph, registry publication, or protected branch permission. Missing required local tooling is provisioned from the repo lock or recorded as an infrastructure failure; it is never silently skipped.

**Release/acceptance gates** may use a contributor-owned environment: real graph client and connector receipts, strict Pages build/publication, online vulnerability audit, and artifact publication. These report `PASS`, `FAIL`, or `NOT RUN` separately from pull-request source status. A live acceptance failure blocks acceptance/release, not review of source changes. The release job must verify published wheel digest, installed consumer import and generated DTO compatibility; a local source overlay cannot pass it.

Public-doc privacy scanning searches Markdown, HTML source, examples and generated Pages inputs for private address ranges, host aliases, environment-only domains, credential strings, and machine paths. Test the scanner with planted violations to prove a red result. Synthetic RFC 5737/3849 addresses and `example.com` are allowed fixtures. Keep links relative or public. Pages navigation and SDK API docs must describe the exact released source, not a future design as current behavior.

## Fresh-checkout workflow

Install Python and `uv` as pinned in `pyproject.toml`; run `uv sync`, `uv run --frozen python -m pytest -q`, lint/type/wiring hooks, and `python -m build` or the repository's pinned wheel command. The Pages source build runs in CI with its declared theme dependency. Contributors may run it locally using the same lock, but source PR validation never assumes a pre-existing sibling checkout.

## Evidence and completion

| Gate | State | Evidence |
|---|---|---|
| Portable cloud PR gate | OPEN | Pending exact CI run |
| Planted privacy scanner violations | OPEN | Pending focused test |
| Published Pages and wheel consumer | OPEN | Pending URLs, artifact digest and release run |

**LANDED** means exact merged gate and docs source. **ACCEPTED** means cloud PR tests pass from fresh checkout and release evidence passes independently. Removing a stale gate does not waive source correctness checks.
