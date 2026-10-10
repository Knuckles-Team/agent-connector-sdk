#!/usr/bin/env python3
"""Plan an isolated-consumer compatibility check for the built release wheel.

SDK-QUALITY-RELEASE-R001: the release job must verify the installed SDK
wheel's generated-type and native-kernel compatibility against the published,
version-compatible graph-client wheel in an isolated installed consumer --
never a source overlay (the repository checkout on ``sys.path``). A source
overlay can hide a packaging regression that only an installed wheel exposes
(missing package data, a stale generated contract baked into the sdist, an
extras mismatch).

This module provides the two pure building blocks the CI step composes:

``pinned_graph_client_requirement``
    The exact ``graph-client`` version requirement this SDK release declares,
    read from ``pyproject.toml`` -- the one place that pin is allowed to live.

``isolated_install_plan``
    The ordered list of commands that build the isolated consumer: a fresh
    virtual environment (never the development environment this process is
    running in), installed *only* from the built wheel path plus the pinned
    graph-client requirement, with no ``-e``/path install of either.

Usage: ``python3 scripts/check_wheel_consumer_compatibility.py --wheel
dist/*.whl`` -- exit 0 once the isolated consumer imports the generated
contracts and the native kernel successfully, exit 2 if the universe (a built
wheel, a pinned graph-client requirement) cannot be established.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"

_IMPORT_SMOKE = (
    "import epistemic_graph.generated.source_ingestion as _c; "
    "import epistemic_graph.native as _k; "
    "assert _c and _k"
)


class CompatibilityGateError(RuntimeError):
    """The isolated-consumer compatibility universe could not be established."""


def pinned_graph_client_requirement(pyproject_text: str | None = None) -> str:
    """Return the exact ``graph-client`` dependency requirement string.

    Reads ``[project.dependencies]`` (or an optional extra) in
    ``pyproject.toml`` rather than a value copied into this script, so a
    version bump never needs a script edit.
    """
    text = pyproject_text if pyproject_text is not None else PYPROJECT.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    candidates: list[str] = list(data.get("project", {}).get("dependencies", []))
    for extra_deps in data.get("project", {}).get("optional-dependencies", {}).values():
        candidates.extend(extra_deps)
    for requirement in candidates:
        if re.match(r"^epistemic-graph(\[[^\]]*\])?\s*[=<>!~]", requirement):
            return requirement
    raise CompatibilityGateError(
        "pyproject.toml declares no epistemic-graph (graph-client) requirement to pin against"
    )


def isolated_install_plan(wheel_path: Path, graph_client_requirement: str, venv_dir: Path) -> list[list[str]]:
    """Return the shell command plan for an isolated installed consumer.

    Every step targets ``venv_dir`` explicitly and installs from a built
    artifact path or a published requirement string -- never ``-e .`` and
    never the repository root -- so the check exercises what a real consumer
    receives, not this source overlay.
    """
    if not str(wheel_path).endswith(".whl"):
        raise CompatibilityGateError(f"not a built wheel: {wheel_path}")
    return [
        ["uv", "venv", "--clear", str(venv_dir)],
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(venv_dir),
            str(wheel_path),
            graph_client_requirement,
        ],
        ["uv", "run", "--python", str(venv_dir), "python3", "-c", _IMPORT_SMOKE],
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, help="path to the built SDK wheel")
    parser.add_argument(
        "--venv",
        default="dist-consumer-venv",
        help="isolated venv directory to build and install into (default: dist-consumer-venv)",
    )
    args = parser.parse_args(argv)

    try:
        requirement = pinned_graph_client_requirement()
        plan = isolated_install_plan(Path(args.wheel), requirement, Path(args.venv))
    except CompatibilityGateError as error:
        print(f"check_wheel_consumer_compatibility: CANNOT RUN: {error}", file=sys.stderr)
        return 2

    import subprocess

    for command in plan:
        print("+", " ".join(command))
        subprocess.run(command, check=True, cwd=ROOT)
    print("check_wheel_consumer_compatibility: isolated consumer import OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
