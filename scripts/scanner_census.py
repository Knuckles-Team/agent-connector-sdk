#!/usr/bin/env python3
"""Absolute cccc and KISS census over every tracked package module.

The staged hooks are diff-scoped so that pre-existing debt elsewhere cannot block
an unrelated commit. This repository starts at zero on both scanners, so the
census enforces zero absolutely: no baseline, no allowlist, and the real totals
are printed on every run. CI runs it in the scanner-quality job.

cccc: every function, including nested children, at cyclomatic <= 10 and
cognitive <= 15 (the fleet caps). KISS: ``.kiss/kiss.toml``, one path per
invocation.

Exit 0 = zero findings, 1 = findings, 2 = cannot run.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kiss_diff_scope import format_violation, parse_report
from scanner_versions import ScannerError, binary

ROOT = Path(__file__).resolve().parents[1]
MAX_CYCLOMATIC = 10
MAX_COGNITIVE = 15


def _modules() -> list[str]:
    output = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--", "agent_connector_sdk/*.py"],
        capture_output=True, text=True, check=True,
    ).stdout
    return sorted(filter(None, output.split("\0")))


def _functions(functions: list[dict[str, Any]], prefix: str = "") -> Iterator[tuple[str, int, int]]:
    for function in functions:
        name = f"{prefix}{function['name']}"
        yield name, int(function["cyclomatic"]), int(function["cognitive"])
        yield from _functions(function.get("children", []), f"{name}.")


def _cccc_findings(cccc: str, path: str) -> tuple[int, list[str]]:
    result = subprocess.run([cccc, "--no-config", "--min", "0", "--lang", "python", path], cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        raise ScannerError(f"cccc failed on {path}")
    document = json.loads(result.stdout)
    rows = [row for file in document["files"] for row in _functions(file["functions"])]
    over = [f"{path}:{name} cyclomatic={cy} cognitive={co}" for name, cy, co in rows if cy > MAX_CYCLOMATIC or co > MAX_COGNITIVE]
    return len(rows), over


def _kiss_findings(kiss: str, path: str) -> list[str]:
    result = subprocess.run([kiss, "check", "--config", ".kiss/kiss.toml", "--lang", "python", path], cwd=ROOT, capture_output=True, text=True, check=False)
    report = result.stdout + result.stderr
    if "Unknown config key" in report or result.returncode not in (0, 1):
        raise ScannerError(f"kiss failed on {path}")
    return [format_violation(v) for v in parse_report(report)]


def main() -> int:
    try:
        cccc, kiss = binary("cccc"), binary("kiss")
        modules = _modules()
        functions, cccc_over, kiss_over = 0, [], []
        for path in modules:
            count, over = _cccc_findings(cccc, path)
            functions += count
            cccc_over.extend(over)
            kiss_over.extend(_kiss_findings(kiss, path))
    except (ScannerError, OSError, subprocess.SubprocessError, json.JSONDecodeError, KeyError) as exc:
        print(f"scanner-census: CANNOT RUN: {exc}", file=sys.stderr)
        return 2
    for line in [*cccc_over, *kiss_over]:
        print(line)
    print(
        f"scanner-census: {len(modules)} modules, {functions} functions; "
        f"cccc over caps: {len(cccc_over)}; kiss findings: {len(kiss_over)}"
    )
    return 1 if cccc_over or kiss_over else 0


if __name__ == "__main__":
    raise SystemExit(main())
