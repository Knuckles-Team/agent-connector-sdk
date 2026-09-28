#!/usr/bin/env bash
set -euo pipefail

# Git exports these for hook processes; without clearing them, `git -C` still
# operates on the SDK repository instead of the nested contract checkout.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR GIT_PREFIX

# This source revision carries the generated contracts consumed by the SDK.
# Fetch it in both hosted CI and local hooks; a second actions/checkout step is
# skipped by the local CI replica and leaves an older published wheel visible.
revision=f17f47ab300f7f1ddd972d4e0214283a28547e36
target=.ci/epistemic-graph

if [ -d "$target/.git" ] &&
  [ "$(git -C "$target" rev-parse HEAD)" = "$revision" ] &&
  [ -f "$target/epistemic_graph/generated/source_ingestion.py" ] &&
  [ -z "$(git -C "$target" status --porcelain)" ]; then
  exit 0
fi

if [ ! -d "$target/.git" ]; then
  mkdir -p .ci
  git clone --filter=blob:none --no-checkout \
    https://github.com/Knuckles-Team/epistemic-graph.git "$target"
fi
if ! git -C "$target" cat-file -e "$revision^{commit}" 2>/dev/null; then
  git -C "$target" fetch --filter=blob:none --depth=1 origin "$revision"
fi
git -C "$target" sparse-checkout set epistemic_graph
git -C "$target" checkout --detach "$revision"
test "$(git -C "$target" rev-parse HEAD)" = "$revision"
test -z "$(git -C "$target" status --porcelain)"
