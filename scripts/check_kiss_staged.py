#!/usr/bin/env python3
# Ported from agent-packages/epistemic-graph/scripts/check_kiss_staged.sh (branch
# refactor/eg-f56-registry-kiss, lane F6) for agent-connector-sdk (RF-ADR-009 lane
# SDK-CORE). Adapted: Python instead of bash; scope is staged agent_connector_sdk/
# Python; the Rust module-closure step does not apply.
"""Changed-source KISS gate: staged package Python, diff-scoped, fail closed.

* Resolves an installed kiss binary at the pinned version; never downloads one.
* Reads only the staged index (materialized with ``git checkout-index``), so an
  unstaged edit can neither hide nor invent a finding.
* Passes ONE path per ``kiss check`` (kiss 0.4.10 reports a false clean for a
  multi-path check) and always ``--config .kiss/kiss.toml`` (without it kiss writes
  a self-calibrating ``.kissconfig``). A tracked ``.kissconfig`` is refused.
* Narrows each report with :mod:`kiss_diff_scope` against the HEAD blob.

Exit 0 = no attributable findings, 1 = attributable findings, 2 = cannot run.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kiss_diff_scope import attributable_violations, format_violation, parse_report
from scanner_versions import ScannerError, binary

ROOT = Path(__file__).resolve().parents[1]
SCOPE = "agent_connector_sdk/"


class CannotRun(RuntimeError):
    """The gate could not produce a trustworthy verdict."""


def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k == "GIT_INDEX_FILE"}


def _git(*args: str, capture: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=capture, env=_env(), check=False)
    if result.returncode != 0:
        raise CannotRun(f"git {args[0]} failed")
    return result


def _changed() -> list[str]:
    output = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").stdout.decode()
    return [p for p in output.split("\0") if p.startswith(SCOPE) and p.endswith(".py")]


def _kiss(kiss: str, tree: Path, path: str) -> str:
    result = subprocess.run(
        [kiss, "check", "--config", str(tree / ".kiss/kiss.toml"), "--lang", "python", path],
        cwd=tree, capture_output=True, text=True, env=_env(), check=False, timeout=300,
    )
    report = result.stdout + result.stderr
    count = len(parse_report(report))
    if "Unknown config key" in report or result.returncode not in (0, 1):
        raise CannotRun(f"kiss failed on {path}: {report.strip()[:300]}")
    if (result.returncode == 0) != (count == 0 and "NO VIOLATIONS" in report):
        raise CannotRun(f"kiss exit status and report disagree for {path}")
    return report


def _materialize(scratch: Path) -> tuple[Path, Path | None]:
    staged = scratch / "index"
    _git("checkout-index", "--all", f"--prefix={staged}/")
    if not (staged / ".kiss/kiss.toml").is_file() or (staged / ".kissconfig").exists():
        raise CannotRun("staged .kiss/kiss.toml missing or a .kissconfig is present")
    if subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", "-q", "HEAD"], capture_output=True, env=_env(), check=False).returncode != 0:
        return staged, None
    head = scratch / "head"
    head.mkdir()
    archive = _git("archive", "HEAD").stdout
    subprocess.run(["tar", "-x", "-C", str(head)], input=archive, check=True)
    return staged, head


def _attributable(kiss: str, staged: Path, head: Path | None, path: str) -> list[dict[str, str]]:
    report = _kiss(kiss, staged, path)
    if not parse_report(report):
        return []
    head_file = head / path if head is not None else None
    head_known = head_file is not None and head_file.is_file()
    return attributable_violations(
        (staged / path).read_text(encoding="utf-8"),
        report,
        head_file.read_text(encoding="utf-8") if head_known and head_file else None,
        _kiss(kiss, head, path) if head_known and head else None,
    )


def main() -> int:
    try:
        paths = _changed()
        if not paths:
            print("kiss(staged): OK — no staged agent_connector_sdk/ Python")
            return 0
        kiss = binary("kiss")
        with tempfile.TemporaryDirectory(prefix="sdk-kiss-staged-") as scratch:
            staged, head = _materialize(Path(scratch))
            findings = [v for path in paths for v in _attributable(kiss, staged, head, path)]
    except (CannotRun, ScannerError, OSError, subprocess.SubprocessError) as exc:
        print(f"kiss(staged): CANNOT RUN: {exc}", file=sys.stderr)
        return 2
    for violation in findings:
        print(format_violation(violation))
    print(f"kiss(staged): {len(findings)} attributable finding(s) across {len(paths)} file(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
