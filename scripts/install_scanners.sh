#!/usr/bin/env bash
# Install the native scanners the pinned Knuckles-Team/pipelines hooks require
# (PINNED_VERSIONS in pipelines_hooks/core/tools.py at the `rev:` in
# .config/pre-commit.yaml). This is the only place the scanner pins live; the
# shared scanner-versions hook proves the installed binaries match them.
# Hosted CI and `scripts/bootstrap.sh --scanners` both call this script, so the
# local and CI toolchains are identical. Binaries are linked into
# ~/.local/bin, the first location the hooks resolve.
#
# Needs cargo (Rust stable) and npm (Node 20+). Idempotent: cargo skips an
# already-installed identical build.
set -euo pipefail

# cccc 1.6.0 is not published to crates.io (cccc-cli stops at 1.0.0): the
# upstream v1.6.0 tag by its immutable commit.
CCCC_GIT=https://github.com/moznion/cccc
CCCC_REV=d728759323be5d9977b7390a27133e8eaf481f26
# kiss: the fleet's own fork build (upstream 0.4.12 + the inline-module
# resolution fix); crates.io 0.4.12 aborts the census (see
# pipelines_hooks/core/kiss_fork.py in Knuckles-Team/pipelines).
KISS_GIT=https://github.com/Knucklessg1/kiss
KISS_REV=7f1c6785697d3fe9a41ceb8b8e5d0f615fb1f3d9
DUPEHOUND_VERSION=0.1.2

for tool in cargo npm git python3 rustup; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "install_scanners.sh: $tool is required (Rust stable / Node 20+)" >&2
    exit 2
  }
done

root="${SCANNER_ROOT:-$HOME/.local/share/pipelines-scanners}"
bin="$HOME/.local/bin"
mkdir -p "$root" "$bin"

cargo install --locked --git "$CCCC_GIT" --rev "$CCCC_REV" --root "$root/cccc" cccc-cli
cargo install --locked --git "$KISS_GIT" --rev "$KISS_REV" --root "$root/kiss" kiss-ai
cargo install --locked --version "$DUPEHOUND_VERSION" --root "$root/dupehound" dupehound
# The shared provider owns jscpd's source, patch, compiler and receipt checks.
# The source installer is bound to the reviewed immutable provider. Shared
# hook references keep their separately required main convention.
provider="$(mktemp -d "$root/pipelines-provider.XXXXXX")"
trap 'rm -rf -- "$provider"' EXIT
provider_git() (
  # Hooks can export repository selectors; never let them redirect this clone.
  for git_name in ${!GIT_@}; do unset "$git_name"; done
  git "$@"
)
provider_commit="c0a089c83eea9d0d08f48e6c00681eb989268d9a"
provider_git -C "$provider" init --quiet
provider_git -C "$provider" fetch --depth 1 \
  https://github.com/Knuckles-Team/pipelines.git "$provider_commit" >&2
provider_git -C "$provider" checkout --quiet --detach FETCH_HEAD
provider_revision="$(provider_git -C "$provider" rev-parse HEAD)"
if [[ "$provider_revision" != "$provider_commit" ]]; then
  echo "Scanner provider revision mismatch" >&2
  exit 1
fi
printf 'Scanner provider revision: %s\n' "$provider_revision" >&2
toolchain="$(python3 - "$provider" <<'PYTHON'
import sys
sys.path.insert(0, sys.argv[1])
from pipelines_hooks.core.jscpd_build import RUST_TOOLCHAIN
print(RUST_TOOLCHAIN)
PYTHON
)"
rustup toolchain install "$toolchain" --profile minimal >&2
jscpd_bin_dir="$(python3 "$provider/scripts/install_jscpd.py" --root "$root/jscpd")"

ln -sf "$root/cccc/bin/cccc" "$bin/cccc"
ln -sf "$root/kiss/bin/kiss" "$bin/kiss"
ln -sf "$root/dupehound/bin/dupehound" "$bin/dupehound"
ln -sf "$jscpd_bin_dir/jscpd" "$bin/jscpd"

for tool in cccc kiss dupehound jscpd; do
  printf '%s: ' "$tool"
  "$bin/$tool" --version
done
