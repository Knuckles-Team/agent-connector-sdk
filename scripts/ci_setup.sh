#!/usr/bin/env bash
# Hosted/CI setup for the shared gates workflow: pinned Python, the locked
# environment (epistemic-graph from its PyPI wheel), and the operator-owned
# identity catalog for tracked-privacy.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

CI=true bash scripts/bootstrap.sh

# The prohibited-identity catalog arrives through a repository variable. A
# missing catalog fails closed except on a fork pull request, which cannot read it.
if [ -n "${PROHIBITED_IDENTITY_CATALOG:-}" ]; then
  mkdir -p "$HOME/.config/arbora/governance"
  printf '%s' "$PROHIBITED_IDENTITY_CATALOG" > "$HOME/.config/arbora/governance/prohibited-identities.json"
elif [ "${FORK_PULL_REQUEST:-false}" != "true" ]; then
  echo "tracked-privacy: CANNOT RUN: the PROHIBITED_IDENTITY_CATALOG repository variable is not set" >&2
  exit 2
fi
