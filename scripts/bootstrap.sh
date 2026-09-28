#!/usr/bin/env bash
# One-command contributor setup for agent-connector-sdk.
#
#   scripts/bootstrap.sh              pinned Python, locked env, EG contract, git hooks
#   scripts/bootstrap.sh --scanners   additionally the pinned native scanners
#
# Idempotent and non-interactive. Needs git, python3 and curl; installs uv >= 0.9.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

scanners=false
for arg in "$@"; do
  case "$arg" in
    --scanners) scanners=true ;;
    -h | --help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "bootstrap.sh: unknown argument: $arg" >&2; exit 2 ;;
  esac
done

export PATH="$HOME/.local/bin:$PATH"

# uv >= 0.9: older releases cannot fetch current CPython patch releases. Prefer a
# user-level pip upgrade; fall back to the astral release installer, verified
# against its digest before it runs (the version hosted CI pins in
# .github/workflows/).
uv_minimum=0.9
uv_version=0.11.7
uv_installer_sha256=efed99618cb5c31e4e36a700ab7c3698e83c0ae0f3c336714043d0f932c8d32c
uv_is_current() {
  command -v uv >/dev/null 2>&1 || return 1
  local have
  have=$(uv --version | awk '{print $2}')
  [ "$(printf '%s\n%s\n' "$uv_minimum" "$have" | sort -V | head -n1)" = "$uv_minimum" ]
}
if ! uv_is_current; then
  python3 -m pip install --user --quiet --upgrade "uv>=$uv_minimum" 2>/dev/null ||
    python3 -m pip install --user --quiet --upgrade --break-system-packages "uv>=$uv_minimum" 2>/dev/null ||
    true
  hash -r
fi
if ! uv_is_current; then
  installer=$(mktemp)
  trap 'rm -f "$installer"' EXIT
  curl -LsSf -o "$installer" \
    "https://github.com/astral-sh/uv/releases/download/$uv_version/uv-installer.sh"
  echo "$uv_installer_sha256  $installer" | sha256sum -c --quiet -
  UV_NO_MODIFY_PATH=1 sh "$installer"
  hash -r
fi
uv_is_current || { echo "bootstrap.sh: uv >= $uv_minimum is required" >&2; exit 2; }

# The pinned interpreter is the lower bound of requires-python.
python_version=$(sed -n 's/^requires-python = ">=\([0-9.]*\).*/\1/p' pyproject.toml)
uv python install "$python_version"

# The SDK consumes epistemic-graph's generated contract from a pinned source
# checkout (.ci/epistemic-graph), exactly as hosted CI does.
bash scripts/bootstrap_epistemic_graph_contract.sh
uv sync --frozen --group test --python "$python_version" --no-install-package epistemic-graph

# Put the pinned contract first on sys.path in the project environment (ahead of
# any published epistemic-graph wheel `uv run` may install), so plain
# `uv run pytest` behaves like CI's PYTHONPATH=.ci/epistemic-graph.
site_packages=$(uv run --frozen --no-sync python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
printf 'import sys; sys.path.insert(0, %s)\n' "'$PWD/.ci/epistemic-graph'" > "$site_packages/_epistemic_graph_contract.pth"

# Git hooks are a contributor convenience; hosted CI runs the stages directly.
if [ -z "${CI:-}" ]; then
  uvx --from pre-commit==4.6.0 pre-commit install --config .config/pre-commit.yaml \
    --hook-type pre-commit --hook-type pre-push
fi

if [ "$scanners" = true ]; then
  bash scripts/install_scanners.sh
fi

echo "bootstrap complete: run 'uvx --from pre-commit==4.6.0 pre-commit run --all-files --config .config/pre-commit.yaml'"
