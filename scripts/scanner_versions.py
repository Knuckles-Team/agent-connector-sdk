#!/usr/bin/env python3
"""Verify installed scanner binaries against the versions pinned in pyproject.toml.

Pins mirror epistemic-graph's ``scripts/scanner_contract.py``: cccc 1.6.0,
kiss 0.4.10, dupehound 0.1.2, jscpd 5.0.16. cccc and kiss are pinned in
``[tool.agent_connector_sdk.scanners]``; dupehound and jscpd in
``[tool.agent_connector_sdk.clone_scanners]`` (read by the clone wrappers).

Hooks never install tools. A missing binary or a different version is an
environment failure (exit 2), never a clean pass.

Usage::

    python3 scripts/scanner_versions.py verify cccc kiss dupehound jscpd
    python3 scripts/scanner_versions.py binary kiss    # print the verified path
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_OUTPUT_PREFIX = {"cccc": "cccc", "kiss": "kiss", "dupehound": "dupehound", "jscpd": "cpd"}
_TABLE = {"cccc": "scanners", "kiss": "scanners", "dupehound": "clone_scanners", "jscpd": "clone_scanners"}


class ScannerError(RuntimeError):
    """A scanner is missing, unpinned, or at the wrong version."""


def pinned_version(tool: str) -> str:
    """The version pinned for ``tool``."""
    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    table = document.get("tool", {}).get("agent_connector_sdk", {}).get(_TABLE[tool], {})
    version = table.get(f"{tool}_version")
    if not isinstance(version, str) or not version:
        raise ScannerError(f"{tool}_version is not pinned in pyproject.toml")
    return version


def binary(tool: str) -> str:
    """The installed binary for ``tool`` after verifying its version."""
    override = os.environ.get(f"{tool.upper()}_BIN")
    candidates = [override] if override else [shutil.which(tool), str(Path.home() / ".local/bin" / tool), str(Path.home() / ".cargo/bin" / tool)]
    found = next((c for c in candidates if c and Path(c).is_file() and os.access(c, os.X_OK)), None)
    if found is None:
        raise ScannerError(f"{tool} is not installed; install the pinned binary (hooks never download it)")
    result = subprocess.run([found, "--version"], capture_output=True, text=True, check=False, timeout=30)
    expected = f"{_OUTPUT_PREFIX[tool]} {pinned_version(tool)}"
    if result.returncode != 0 or result.stdout.strip() != expected:
        raise ScannerError(f"{tool}: expected {expected!r}, got {result.stdout.strip()!r}")
    return found


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in {"verify", "binary"} or any(t not in _TABLE for t in argv[1:]):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        paths = [binary(tool) for tool in argv[1:]]
    except (ScannerError, OSError, subprocess.TimeoutExpired, tomllib.TOMLDecodeError) as exc:
        print(f"scanner-versions: CANNOT RUN: {exc}", file=sys.stderr)
        return 2
    if argv[0] == "binary":
        print(paths[0])
    else:
        print("scanner-versions: OK — " + ", ".join(f"{t} {pinned_version(t)}" for t in argv[1:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
