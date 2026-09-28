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
KISS_VERSION=0.4.10
DUPEHOUND_VERSION=0.1.2
JSCPD_VERSION=5.0.16

for tool in cargo npm; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "install_scanners.sh: $tool is required (Rust stable / Node 20+)" >&2
    exit 2
  }
done

root="${SCANNER_ROOT:-$HOME/.local/share/pipelines-scanners}"
bin="$HOME/.local/bin"
mkdir -p "$root" "$bin"

cargo install --locked --git "$CCCC_GIT" --rev "$CCCC_REV" --root "$root/cccc" cccc-cli
cargo install --locked --version "$KISS_VERSION" --root "$root/kiss" kiss-ai
cargo install --locked --version "$DUPEHOUND_VERSION" --root "$root/dupehound" dupehound
npm install --prefix "$root/npm" --no-package-lock --ignore-scripts --no-save \
  --no-audit --no-fund "jscpd@$JSCPD_VERSION"

ln -sf "$root/cccc/bin/cccc" "$bin/cccc"
ln -sf "$root/kiss/bin/kiss" "$bin/kiss"
ln -sf "$root/dupehound/bin/dupehound" "$bin/dupehound"
ln -sf "$root/npm/node_modules/.bin/jscpd" "$bin/jscpd"

for tool in cccc kiss dupehound jscpd; do
  printf '%s: ' "$tool"
  "$bin/$tool" --version
done
