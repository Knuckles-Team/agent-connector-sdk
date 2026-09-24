"""The shared command-line shell of the SDK's documentation gates.

Each gate supplies ``violations(root)`` plus its names; this runs it over
``--root`` (default: this repository) and maps the result to the gate exit
contract: 0 = clean, 1 = findings, 2 = the gate could not run.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DocGate:
    """One documentation gate: what it checks and how it names itself."""

    description: str | None
    label: str
    title: str
    violations: Callable[[Path], list[str]]
    errors: tuple[type[BaseException], ...]


def run(gate: DocGate, argv: list[str] | None = None) -> int:
    """Parse ``--root``, run ``gate``, and report in the gate exit contract."""
    parser = argparse.ArgumentParser(description=gate.description)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    root = parser.parse_args(argv).root.resolve()
    try:
        failures = gate.violations(root)
    except (*gate.errors, OSError, UnicodeDecodeError) as exc:
        print(f"{gate.label}: CANNOT RUN: {exc}", file=sys.stderr)
        return 2
    if failures:
        print(f"{gate.title} failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"{gate.title} passed")
    return 0
