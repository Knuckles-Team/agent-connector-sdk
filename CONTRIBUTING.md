# Contributing to agent-connector-sdk

[`AGENTS.md`](AGENTS.md) is the engineering contract: what this repository
owns, its module map, and the rules every change preserves. This page covers
setup and the change flow.

## Setup

```bash
git clone https://github.com/Knuckles-Team/agent-connector-sdk.git
cd agent-connector-sdk
scripts/bootstrap.sh
```

`scripts/bootstrap.sh` is idempotent. It ensures uv >= 0.9, installs the pinned
Python, fetches the pinned epistemic-graph contract source into
`.ci/epistemic-graph`, runs `uv sync --frozen` with the test dependencies, and
installs the pre-commit and pre-push git hooks from `.config/pre-commit.yaml`.
Add `--scanners` to also install the pinned native scanners (cccc, KISS,
dupehound, jscpd) through `scripts/install_scanners.sh`; that needs cargo and
npm.

## Running the gates

```bash
uv run --frozen python -m pytest -q
uvx --from pre-commit==4.6.0 pre-commit run --config .config/pre-commit.yaml --all-files
uvx --from pre-commit==4.6.0 pre-commit run --config .config/pre-commit.yaml --all-files --hook-stage pre-push
```

Hosted CI runs this same configuration, so a clean local run predicts a clean
CI run. Manual-stage gates (native scanners, tracked privacy, fleet dependency
order) run with `--hook-stage manual`. A manual gate whose prerequisite is
missing locally prints `SKIPPED (<gate>): <reason>`; in CI it fails closed.
See [`docs/quality-gates.md`](docs/quality-gates.md) for what each gate checks.

## Branches and pull requests

1. Branch from `main` (use a separate `git worktree` when working on multiple
   changes at once; never `git stash`).
2. Stage explicit paths, run the gates, and commit in logical steps. Never use
   `--no-verify`.
3. Push the branch and open a pull request against `main`, as a draft until
   the gates pass locally.
4. The `gates` and `build` jobs must pass before merge; `scanner-quality` is
   advisory. Releases are cut from `vX.Y.Z` tags by maintainers.
