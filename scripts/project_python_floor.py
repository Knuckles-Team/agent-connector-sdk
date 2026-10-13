#!/usr/bin/env python3
"""Print the lower bound from a project's own requires-python field."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

_LOWER_BOUND = re.compile(r"\s*>=\s*(\d+(?:\.\d+){1,2})\s*")


def project_python_floor(path: Path) -> str:
    """Read the single simple lower bound from [project].requires-python."""
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    project = document.get("project")
    if not isinstance(project, dict):
        raise ValueError("pyproject.toml has no [project] table")
    requirement = project.get("requires-python")
    if not isinstance(requirement, str):
        raise ValueError("[project].requires-python must be a string")
    bounds = [
        match.group(1)
        for clause in requirement.split(",")
        if (match := _LOWER_BOUND.fullmatch(clause))
    ]
    if len(bounds) != 1:
        raise ValueError(
            "[project].requires-python must contain one simple >= version bound"
        )
    return bounds[0]


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: project_python_floor.py pyproject.toml", file=sys.stderr)
        return 2
    try:
        version = project_python_floor(Path(sys.argv[1]))
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        print(f"project_python_floor.py: {exc}", file=sys.stderr)
        return 2
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
