#!/usr/bin/env bash
set -euo pipefail

# Git exports these for hook processes; without clearing them, `git -C` still
# operates on the SDK repository instead of the nested theme checkout.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR GIT_PREFIX

# The shared Pages theme the mkdocs-build gate inherits (SDK-CONNECTOR-CONTROL-R018):
# the same templates/mkdocs-theme the Pages workflow vendors via
# pages_pipeline.yml, so a local or CI docs build sees the identical base
# config a merged push to main would render with. pipelines is referenced at
# main, never SHA-pinned (per workspace convention), so this always re-fetches
# rather than caching a fixed revision.
target=.pipeline-theme

rm -rf "$target"
mkdir -p "$target"
git clone --filter=blob:none --no-checkout --depth=1 --branch main \
  https://github.com/Knuckles-Team/pipelines.git "$target"
git -C "$target" sparse-checkout set templates/mkdocs-theme
git -C "$target" checkout main
test -f "$target/templates/mkdocs-theme/base.mkdocs.yml"
