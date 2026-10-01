"""Shared command-line driver for documentation gates.

A gate supplies ``violations(root) -> list[str]``. The driver resolves the
repository root, distinguishes "the gate could not run" (exit 2) from "the
gate found violations" (exit 1), and prints a uniform report.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path


class GateError(RuntimeError):
    """The gate could not establish its universe."""


def run_gate(
    name: str,
    description: str | None,
    violations: Callable[[Path], list[str]],
    argv: list[str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    root = parser.parse_args(argv).root.resolve()
    try:
        failures = violations(root)
    except (GateError, OSError, UnicodeDecodeError) as exc:
        print(f"{name}: CANNOT RUN: {exc}", file=sys.stderr)
        return 2
    if failures:
        print(f"{name} gate failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"{name} gate passed")
    return 0
