#!/usr/bin/env python3
"""Fail closed when a tracked package module is reachable from nothing.

The Python counterpart of epistemic-graph's ``scripts/check_orphan_modules.py``
(which walks cargo's compiler-declared module closure). Every shape scanner
measures source that exists; none notices a module that nothing uses. A module
that is short, simple and untested-by-omission is still dead weight, and in an
SDK it is worse: it looks like public API.

The property
------------
A tracked module under ``agent_connector_sdk/`` is reachable when it is:

* a declared root: a module listed in ``[tool.agent_connector_sdk.wiring]
  public_modules`` in ``pyproject.toml`` (the SDK's documented public surface),
  or the target module of a ``[project.entry-points]`` value; or
* imported, directly or transitively, by a reachable module (absolute and
  relative imports, including function-local and ``TYPE_CHECKING`` imports:
  reachability, not load order, is the question here).

A package ``__init__`` is reachable when any module inside it is. Everything
else is reported. There is no allowlist: an unreachable module is either wired,
declared public (and then the public-API gate requires tests for it), or deleted.

Usage: ``python3 scripts/check_orphan_modules.py [--root REPO]``.
Exit 0 = no orphans, 1 = orphans found, 2 = the gate could not establish its
universe (never reported as clean).
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
import tomllib
from pathlib import Path

PACKAGE = "agent_connector_sdk"


class GateError(RuntimeError):
    """The gate could not establish its universe."""


def _tracked_modules(root: Path) -> dict[str, Path]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--cached", "-z", "--", f"{PACKAGE}/*.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GateError(f"git ls-files failed: {result.stderr.strip()[:200]}")
    modules: dict[str, Path] = {}
    for rel in filter(None, result.stdout.split("\0")):
        parts = list(Path(rel).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        modules[".".join(parts)] = root / rel
    if not modules:
        raise GateError(f"no tracked modules under {PACKAGE}/")
    return modules


def _declared_roots(root: Path) -> set[str]:
    try:
        document = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise GateError(f"cannot read pyproject.toml: {exc}") from exc
    wiring = document.get("tool", {}).get(PACKAGE, {}).get("wiring", {})
    public = wiring.get("public_modules")
    if not isinstance(public, list) or not all(isinstance(m, str) for m in public):
        raise GateError(f"[tool.{PACKAGE}.wiring] public_modules must be a list of strings")
    roots = {PACKAGE, *public}
    for group in document.get("project", {}).get("entry-points", {}).values():
        roots.update(str(target).split(":", 1)[0].strip() for target in group.values())
    return roots


def _resolve(module: str, level: int, current: str, is_package: bool) -> str:
    if level == 0:
        return module
    base = current.split(".") if is_package else current.split(".")[:-1]
    base = base[: len(base) - (level - 1)]
    return ".".join([*base, module] if module else base)


def _imports(name: str, path: Path, modules: dict[str, Path]) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    is_package = path.name == "__init__.py"
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            target = _resolve(node.module or "", node.level, name, is_package)
            found.add(target)
            found.update(f"{target}.{alias.name}" for alias in node.names)
    return {candidate for candidate in found if candidate in modules}


def orphans(root: Path) -> list[str]:
    """Tracked modules unreachable from the declared roots."""
    modules = _tracked_modules(root)
    roots = _declared_roots(root)
    missing = sorted(r for r in roots if r.startswith(PACKAGE) and r not in modules)
    if missing:
        raise GateError(f"declared roots do not exist: {', '.join(missing)}")
    reachable: set[str] = set()
    pending = [r for r in roots if r in modules]
    while pending:
        current = pending.pop()
        if current in reachable:
            continue
        reachable.add(current)
        parts = current.split(".")
        pending.extend(".".join(parts[:i]) for i in range(1, len(parts)))
        pending.extend(_imports(current, modules[current], modules) - reachable)
    return sorted(set(modules) - reachable)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        found = orphans(args.root.resolve())
    except (GateError, SyntaxError, OSError) as exc:
        print(f"orphan-modules: CANNOT RUN: {exc}", file=sys.stderr)
        return 2
    if found:
        print("orphan-modules: FAILED — modules reachable from no declared root:")
        for module in found:
            print(f"  - {module}")
        print(
            "Import it from a reachable module, declare it in "
            f"[tool.{PACKAGE}.wiring] public_modules, or delete it."
        )
        return 1
    print("orphan-modules: OK — every tracked module is reachable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
