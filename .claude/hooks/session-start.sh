#!/usr/bin/env bash
# Claude Code on the web: provision a fresh cloud session so tests and the
# pre-commit gates run exactly as they do for a contributor after
# scripts/bootstrap.sh. Local sessions are left untouched.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "${BASH_SOURCE[0]}")/../..}"
bash scripts/bootstrap.sh

if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PATH=\"$HOME/.local/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi
