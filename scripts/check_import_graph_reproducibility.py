#!/usr/bin/env python3
"""Reproduce hosted CI's exact pinned dependency import graph locally.

SDK-QUALITY-RELEASE-R005: a contributor running the pinned install command
from the top-level README (``uv sync --frozen``) must resolve the identical
set of importable distributions -- same names, same versions -- that hosted
CI resolved, so local verification never silently drifts from the hosted
release check. Both sides install from the same committed ``uv.lock``, so the
graph is deterministic by construction; this script makes that graph an
explicit, comparable artifact instead of an implicit assumption.

``compute_import_graph`` returns the sorted ``name==version`` list of every
distribution installed in the current interpreter (the pinned environment
``uv sync --frozen`` built). Hosted CI's recorded result is committed at
``tests/fixtures/pinned_import_graph.txt`` (regenerate it with
``--record`` whenever ``uv.lock`` changes, from a hosted or an equivalently
pinned run); a local run that drifts from that recording -- a stale lock, an
unpinned extra, an environment leak -- fails loudly instead of silently.

Usage: ``python3 scripts/check_import_graph_reproducibility.py`` (compare) or
``--record`` (rewrite the fixture from the current pinned environment).
"""

from __future__ import annotations

import argparse
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "pinned_import_graph.txt"


def compute_import_graph() -> list[str]:
    """Return the sorted ``name==version`` graph of the current environment."""
    seen: dict[str, str] = {}
    for dist in metadata.distributions():
        name = dist.metadata.get("Name")
        version = dist.version
        if name and version:
            seen[name.lower()] = f"{name.lower()}=={version}"
    return sorted(seen.values())


def read_recorded_graph(fixture: Path = FIXTURE) -> list[str]:
    return [line for line in fixture.read_text(encoding="utf-8").splitlines() if line]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record",
        action="store_true",
        help="rewrite the recorded fixture from the current pinned environment",
    )
    args = parser.parse_args(argv)

    live = compute_import_graph()
    if args.record:
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text("\n".join(live) + "\n", encoding="utf-8")
        print(f"check_import_graph_reproducibility: recorded {len(live)} distributions to {FIXTURE}")
        return 0

    if not FIXTURE.exists():
        print(
            f"check_import_graph_reproducibility: CANNOT RUN: no recorded graph at {FIXTURE}; run with --record first",
            file=sys.stderr,
        )
        return 2

    recorded = read_recorded_graph()
    if live != recorded:
        only_local = sorted(set(live) - set(recorded))
        only_recorded = sorted(set(recorded) - set(live))
        print("check_import_graph_reproducibility: import graph drifted from the recorded hosted result", file=sys.stderr)
        if only_local:
            print(f"  only in the local resolve: {only_local}", file=sys.stderr)
        if only_recorded:
            print(f"  only in the recorded result: {only_recorded}", file=sys.stderr)
        return 1

    print(f"check_import_graph_reproducibility: {len(live)} distributions match the recorded hosted result")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
