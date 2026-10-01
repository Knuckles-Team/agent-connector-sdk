#!/usr/bin/env python3
"""Check the relocated universal/privacy-safe external-graph architecture docs.

``docs/architecture/universal-graph-connectors.md`` and
``docs/architecture/privacy-safe-ingestion.md`` moved here from agent-utilities'
own ``scripts/check_external_graph_contract.py`` gate (RF-ADR-009: this repo owns
connectors/transport). That gate verified two things about the docs directly: a
fixed set of required content markers (so the page cannot silently drop mention
of a supported backend or the governed-ingestion vocabulary), and an
environment-literal scan (so no live endpoint, filesystem path, or email address
gets checked in as an example). Both checks move here verbatim -- same markers,
same regex -- scoped to the two docs that now live in this repository. See
agent-utilities' own gate for the source-code-level checks (AgentConfig,
connection_registry.py, external_graph_schema.py, ...), which stay there since
that source never moved.

Usage: ``python3 scripts/check_external_graph_contract.py [--root REPO]``.
Exit 0 = clean, 1 = findings, 2 = the gate could not establish its universe.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REQUIRED_MARKERS = (
    "Neo4j/openCypher",
    "Apache AGE",
    "LadybugDB",
    "remote epistemic-graph",
    "GraphQL",
    "ChangeEnvelope",
    "mapping-policy",
)

_ENVIRONMENT_LITERAL_RE = re.compile(
    r"(?i)(?:https?|bolt|neo4j(?:\+s)?|postgres(?:ql)?)://|"
    r"(?:/home/|/Users/|[A-Z]:[\\/]Users[\\/])|"
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"
)

DOC_RELATIVE_PATHS = (
    "docs/architecture/universal-graph-connectors.md",
    "docs/architecture/privacy-safe-ingestion.md",
)


class GateError(RuntimeError):
    """The gate could not establish its universe."""


def environment_literal_violations(root: Path, path: Path, text: str) -> list[str]:
    """Return locations of checked-in endpoint, path, or email literals."""

    return [
        f"{path.relative_to(root)}:{line_number}: environment-specific literal"
        for line_number, line in enumerate(text.splitlines(), 1)
        if _ENVIRONMENT_LITERAL_RE.search(line)
    ]


def _require_markers(
    failures: list[str], root: Path, path: Path, text: str, markers: tuple[str, ...]
) -> None:
    for marker in markers:
        if marker not in text:
            failures.append(f"{path.relative_to(root)}: missing {marker!r}")


def violations(root: Path) -> list[str]:
    docs = tuple(root / relative for relative in DOC_RELATIVE_PATHS)
    missing = [doc for doc in docs if not doc.is_file()]
    if missing:
        raise GateError(
            "expected doc(s) not found: "
            + ", ".join(str(doc.relative_to(root)) for doc in missing)
        )

    failures: list[str] = []
    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        _require_markers(failures, root, doc, text, REQUIRED_MARKERS)
        failures.extend(environment_literal_violations(root, doc, text))
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        failures = violations(root)
    except (GateError, OSError, UnicodeDecodeError) as exc:
        print(f"external-graph contract: CANNOT RUN: {exc}", file=sys.stderr)
        return 2
    if failures:
        print("External graph contract gate failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("External graph contract gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
