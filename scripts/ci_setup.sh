#!/usr/bin/env bash
# Hosted/CI setup for the shared gates workflow: pinned Python, locked
# environment, the pinned epistemic-graph contract, PYTHONPATH, and the
# operator-owned identity catalog for tracked-privacy.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

CI=true bash scripts/bootstrap.sh
echo "PYTHONPATH=.ci/epistemic-graph" >> "${GITHUB_ENV:-/dev/null}"
PYTHONPATH=.ci/epistemic-graph uv run --frozen --no-sync python -c "from pathlib import Path; import epistemic_graph.generated.source_ingestion as source; assert '.ci/epistemic-graph' in str(Path(source.__file__).resolve())"

# The prohibited-identity catalog arrives through a repository variable. A
# missing catalog fails closed except on a fork pull request, which cannot read it.
if [ -n "${PROHIBITED_IDENTITY_CATALOG:-}" ]; then
  mkdir -p "$HOME/.config/agent-utilities/governance"
  printf '%s' "$PROHIBITED_IDENTITY_CATALOG" > "$HOME/.config/agent-utilities/governance/prohibited-identities.json"
elif [ "${FORK_PULL_REQUEST:-false}" != "true" ]; then
  echo "tracked-privacy: CANNOT RUN: the PROHIBITED_IDENTITY_CATALOG repository variable is not set" >&2
  exit 2
fi
