#!/usr/bin/env python3
"""Fail when a public SDK symbol is never used by the test suite.

Reachable is not invoked: a public function that no test calls is a promise the
repository has not checked. This gate asks the narrow, mechanical question that
catches the common case: does every public name appear as a *used* identifier
(a name, an attribute, or a keyword argument; not only an import line) somewhere
under ``tests/``?

Public names of a module are its ``__all__`` when declared, otherwise its
top-level functions, classes and upper-case constants that do not start with
``_``. Test usage is collected from the AST of every tracked ``tests/**.py``
file, excluding ``import`` statements.

What it does not prove: that the test asserts anything meaningful about the
symbol. That is review's job; this gate keeps the floor from being zero.

Usage: ``python3 scripts/check_public_api_tested.py [--root REPO]``.
Exit 0 = every public name is used by a test, 1 = some are not, 2 = cannot run.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

PACKAGE = "agent_connector_sdk"


def _tracked(root: Path, pattern: str) -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--cached", "-z", "--", pattern],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {result.stderr.strip()[:200]}")
    return [root / rel for rel in filter(None, result.stdout.split("\0"))]


def _declared_all(tree: ast.Module) -> list[str] | None:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            return [str(name) for name in ast.literal_eval(node.value)]
    return None


def _defined_names(node: ast.stmt) -> list[str]:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return [node.name]
    if not isinstance(node, ast.Assign):
        return []
    return [t.id for t in node.targets if isinstance(t, ast.Name) and t.id.isupper()]


def public_names(path: Path) -> list[str]:
    """The public names a module exports."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    declared = _declared_all(tree)
    if declared is not None:
        return declared
    names = [name for node in tree.body for name in _defined_names(node)]
    return [name for name in names if not name.startswith("_")]


def used_identifiers(paths: list[Path]) -> set[str]:
    """Identifiers used outside import statements in ``paths``."""
    used: set[str] = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                used.add(node.attr)
            elif isinstance(node, ast.keyword) and node.arg:
                used.add(node.arg)
    return used


def untested(root: Path) -> list[str]:
    """``module:name`` for every public name no test uses."""
    modules = _tracked(root, f"{PACKAGE}/*.py")
    tests = _tracked(root, "tests/*.py")
    if not modules or not tests:
        raise RuntimeError("no tracked package modules or tests")
    used = used_identifiers(tests)
    missing: list[str] = []
    for path in sorted(modules):
        module = ".".join(path.relative_to(root).with_suffix("").parts)
        missing.extend(f"{module}:{name}" for name in public_names(path) if name not in used)
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        missing = untested(args.root.resolve())
    except (RuntimeError, SyntaxError, OSError, ValueError) as exc:
        print(f"public-api-tested: CANNOT RUN: {exc}", file=sys.stderr)
        return 2
    if missing:
        print(f"public-api-tested: FAILED — {len(missing)} public name(s) used by no test:")
        for entry in missing:
            print(f"  - {entry}")
        return 1
    print("public-api-tested: OK — every public name is used by a test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
