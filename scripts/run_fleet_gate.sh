#!/usr/bin/env bash
# Maintainer-only fleet gates (manual pre-commit stage): dependency-readiness
# and phase-direction. Both need the workspace checkout layout -- a sibling
# agents/repository-manager checkout and, for phase-direction, a workspace.yml
# above this repository. Outside that layout (a standalone clone, a fork, a
# cloud session) the gate cannot run: locally it reports SKIPPED and exits 0;
# with CI set it fails closed (exit 2).
set -euo pipefail

gate="${1:?usage: run_fleet_gate.sh dependency-readiness|phase-direction}"

cannot_run() {
  if [ -n "${CI:-}" ]; then
    echo "$gate: CANNOT RUN: $1" >&2
    exit 2
  fi
  echo "SKIPPED ($gate): $1; this is a maintainer gate that needs the fleet workspace checkout"
  exit 0
}

canonical=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")
manager="$(dirname "$canonical")/agents/repository-manager"
[ -d "$manager" ] || cannot_run "no sibling checkout at $manager"
command -v uv >/dev/null 2>&1 || cannot_run "uv is not installed; run scripts/bootstrap.sh"

# --no-cache: uv otherwise reuses a stale build of the local repository-manager.
run=(uv run --no-cache --no-project --python 3.12 --prerelease=allow --with "$manager")

case "$gate" in
  dependency-readiness)
    exec "${run[@]}" python -m repository_manager.dependency_readiness .
    ;;
  phase-direction)
    workspace="$canonical"
    while [ "$workspace" != / ] && [ ! -f "$workspace/workspace.yml" ]; do
      workspace=$(dirname "$workspace")
    done
    [ -f "$workspace/workspace.yml" ] || cannot_run "no workspace.yml above $canonical"
    exec "${run[@]}" python -m repository_manager.repository_manager \
      --phase-direction-here -f "$workspace/workspace.yml" -w "$workspace" \
      --phase-direction-start "$PWD"
    ;;
  *)
    echo "run_fleet_gate.sh: unknown gate: $gate" >&2
    exit 2
    ;;
esac
