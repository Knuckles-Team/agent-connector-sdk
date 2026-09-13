#!/usr/bin/env python3
"""The SDK's wiring gates: no orphan package module, and every public name tested.

``orphans`` -- a tracked module under ``agent_connector_sdk/`` is reachable when it
is a declared root (a module in ``[tool.agent_connector_sdk.wiring]
public_modules`` or the target module of a ``[project.entry-points]`` value), or
is imported, directly or transitively, by a reachable module (absolute and
relative imports, including function-local and ``TYPE_CHECKING`` imports:
reachability, not load order, is the question). A package ``__init__`` is
reachable when any module inside it is. There is no allowlist: an unreachable
module is wired, declared public (and then its names need tests), or deleted.

``public-api`` -- every public name (``__all__`` when declared, otherwise top-level
functions, classes and upper-case constants not starting with ``_``) must appear
as a used identifier (a name, an attribute or a keyword argument; not only an
import) somewhere in a tracked ``tests/**.py`` file. It keeps the floor from being
zero; whether a test asserts anything meaningful is review's job.

Usage: ``python3 scripts/check_wiring.py {orphans|public-api} [--root REPO]``.
Exit 0 = clean, 1 = findings, 2 = the gate could not establish its universe.
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


def tracked(root: Path, pattern: str) -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--cached", "-z", "--", pattern],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GateError(f"git ls-files failed: {result.stderr.strip()[:200]}")
    return [root / rel for rel in filter(None, result.stdout.split("\0"))]


def tracked_modules(root: Path) -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in tracked(root, f"{PACKAGE}/*.py"):
        parts = list(path.relative_to(root).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        modules[".".join(parts)] = path
    if not modules:
        raise GateError(f"no tracked modules under {PACKAGE}/")
    return modules


def declared_roots(root: Path) -> set[str]:
    try:
        document = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise GateError(f"cannot read pyproject.toml: {exc}") from exc
    public = (
        document.get("tool", {})
        .get(PACKAGE, {})
        .get("wiring", {})
        .get("public_modules")
    )
    if not isinstance(public, list) or not all(isinstance(m, str) for m in public):
        raise GateError(
            f"[tool.{PACKAGE}.wiring] public_modules must be a list of strings"
        )
    roots = {PACKAGE, *public}
    for group in document.get("project", {}).get("entry-points", {}).values():
        roots.update(str(target).split(":", 1)[0].strip() for target in group.values())
    return roots


def _import_targets(node: ast.AST, base: list[str]) -> set[str]:
    """Every module name one import statement could bind (absolute or relative)."""
    if isinstance(node, ast.Import):
        return {alias.name for alias in node.names}
    if not isinstance(node, ast.ImportFrom):
        return set()
    prefix = base[: len(base) - (node.level - 1)] if node.level else []
    target = ".".join([*prefix, node.module] if node.module else prefix)
    return {target, *(f"{target}.{alias.name}" for alias in node.names)}


def imports(name: str, path: Path, modules: dict[str, Path]) -> set[str]:
    """The tracked package modules ``name`` imports anywhere in its body."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    base = name.split(".") if path.name == "__init__.py" else name.split(".")[:-1]
    found = set().union(*(_import_targets(node, base) for node in ast.walk(tree)))
    return found & modules.keys()


def orphans(root: Path) -> list[str]:
    """Tracked modules unreachable from the declared roots."""
    modules = tracked_modules(root)
    roots = declared_roots(root)
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
        pending.extend(imports(current, modules[current], modules) - reachable)
    return sorted(set(modules) - reachable)


DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _assigned(node: ast.stmt) -> list[str]:
    """The plain names a top-level assignment binds."""
    if not isinstance(node, ast.Assign):
        return []
    return [target.id for target in node.targets if isinstance(target, ast.Name)]


def _top_level_names(tree: ast.Module) -> list[str]:
    """Top-level definitions plus upper-case constants."""
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, DEFINITIONS):
            names.append(node.name)
        else:
            names.extend(name for name in _assigned(node) if name.isupper())
    return names


def public_names(path: Path) -> list[str]:
    """The public names a module exports: ``__all__`` when declared."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and "__all__" in _assigned(node):
            return [str(name) for name in ast.literal_eval(node.value)]
    return [name for name in _top_level_names(tree) if not name.startswith("_")]


def used_identifiers(paths: list[Path]) -> set[str]:
    """Identifiers used outside import statements in ``paths``."""
    used: set[str] = set()
    for path in paths:
        for node in ast.walk(
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        ):
            if isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                used.add(node.attr)
            elif isinstance(node, ast.keyword) and node.arg:
                used.add(node.arg)
    return used


def untested(root: Path) -> list[str]:
    """``module:name`` for every public name no test uses."""
    modules = tracked(root, f"{PACKAGE}/*.py")
    tests = tracked(root, "tests/*.py")
    if not modules or not tests:
        raise GateError("no tracked package modules or tests")
    used = used_identifiers(tests)
    return [
        f"{'.'.join(path.relative_to(root).with_suffix('').parts)}:{name}"
        for path in sorted(modules)
        for name in public_names(path)
        if name not in used
    ]


CHECKS = {
    "orphans": (
        orphans,
        "modules reachable from no declared root",
        f"import it, declare it in [tool.{PACKAGE}.wiring] public_modules, or delete it",
    ),
    "public-api": (
        untested,
        "public names used by no test",
        "use each public name in a test, or make it private",
    ),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("check", choices=sorted(CHECKS))
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args(argv)
    run, what, remedy = CHECKS[args.check]
    try:
        findings = run(args.root.resolve())
    except (GateError, SyntaxError, OSError, ValueError) as exc:
        print(f"wiring {args.check}: CANNOT RUN: {exc}", file=sys.stderr)
        return 2
    for finding in findings:
        print(f"  - {finding}")
    if findings:
        print(f"wiring {args.check}: FAILED: {len(findings)} {what}; {remedy}.")
        return 1
    print(f"wiring {args.check}: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
