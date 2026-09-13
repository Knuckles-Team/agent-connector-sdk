#!/usr/bin/env python3
# Ported from agent-packages/epistemic-graph/scripts/kiss_diff_scope.py (branch
# refactor/eg-f56-registry-kiss, lane F6) for agent-connector-sdk (RF-ADR-009 lane
# SDK-CORE). Adapted: Python item spans come from the ast module instead of
# epistemic-graph's Rust lexer; the attribution rules are unchanged.
"""Narrow a KISS report to the findings a staged diff is responsible for.

Bare KISS reports every violation a file carries, so a one-line change to a file
with pre-existing debt would fail for debt it did not touch. This module compares
the staged file's report with a report on the HEAD blob of the same file:

* Rules that live inside one function or class body count only when the
  enclosing item is NEW (no same-named item at HEAD) or MODIFIED (its exact
  source text differs from the same-named item at HEAD). Content, not line
  numbers or names alone, decides; extraction shifts both without changing
  meaning.
* Rules that aggregate a whole file, or a whole class's method count
  (:data:`AGGREGATE_RULES`), count when newly crossed or when the reported
  count grew.

No baseline and no stored number: both reports are computed fresh each run.
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

VIOLATION_RE = re.compile(
    r"^VIOLATION:(?P<rule>[^:]+):(?P<path>[^:]*):(?P<line>\d+):(?P<name>[^:]*):"
    r"\s?(?P<message>.*)$"
)

AGGREGATE_RULES = frozenset(
    {
        "statements_per_file",
        "lines_per_file",
        "functions_per_file",
        "interface_types_per_file",
        "concrete_types_per_file",
        "imported_names_per_file",
        "methods_per_class",
    }
)

_INT_RE = re.compile(r"\d+")
_ITEM_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def item_spans(source: str, name: str) -> list[tuple[int, int, str]]:
    """Every function or class named ``name``: ``(start, end, text)`` in file order.

    Decorators are part of an item's text. A source that does not parse yields no
    spans, which makes every finding in it attributable (fail closed).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    lines = source.splitlines()
    spans: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, _ITEM_TYPES) and node.name == name:
            start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
            end = node.end_lineno or node.lineno
            spans.append((start, end, "\n".join(lines[start - 1 : end])))
    return sorted(spans)


def parse_report(text: str | None) -> list[dict[str, str]]:
    """The ``VIOLATION:`` lines of a KISS report."""
    return [
        match.groupdict()
        for line in (text or "").splitlines()
        if (match := VIOLATION_RE.match(line))
    ]


def _magnitude(message: str) -> int | None:
    match = _INT_RE.search(message)
    return int(match.group()) if match else None


def _head_magnitudes(head: list[dict[str, str]]) -> dict[tuple[str, str], int]:
    magnitudes: dict[tuple[str, str], int] = {}
    for violation in head:
        value = _magnitude(violation["message"])
        if violation["rule"] in AGGREGATE_RULES and value is not None:
            key = (violation["rule"], violation["name"])
            magnitudes[key] = max(magnitudes.get(key, -1), value)
    return magnitudes


def _aggregate_attributable(violation: dict[str, str], head: dict[tuple[str, str], int]) -> bool:
    before = head.get((violation["rule"], violation["name"]))
    after = _magnitude(violation["message"])
    return before is None or (after is not None and after > before)


def _item_attributable(violation: dict[str, str], staged_source: str, head_source: str) -> bool:
    staged = item_spans(staged_source, violation["name"])
    line = int(violation["line"])
    ordinal = next((i for i, (s, e, _) in enumerate(staged) if s <= line <= e), None)
    if ordinal is None:
        return True
    head = item_spans(head_source, violation["name"])
    return ordinal >= len(head) or head[ordinal][2] != staged[ordinal][2]


def attributable_violations(
    staged_source: str,
    staged_report: str,
    head_source: str | None,
    head_report: str | None,
) -> list[dict[str, str]]:
    """The staged findings the diff caused (all of them for a new file)."""
    staged = parse_report(staged_report)
    if head_source is None:
        return staged
    head = _head_magnitudes(parse_report(head_report))
    return [
        violation
        for violation in staged
        if (
            _aggregate_attributable(violation, head)
            if violation["rule"] in AGGREGATE_RULES
            else _item_attributable(violation, staged_source, head_source)
        )
    ]


def format_violation(violation: dict[str, str]) -> str:
    """Render a violation back into KISS's report line format."""
    return (
        f"VIOLATION:{violation['rule']}:{violation['path']}:{violation['line']}:"
        f"{violation['name']}: {violation['message']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--staged-source", required=True, type=Path)
    parser.add_argument("--staged-report", required=True, type=Path)
    parser.add_argument("--head-source", type=Path)
    parser.add_argument("--head-report", type=Path)
    args = parser.parse_args(argv)
    head_source = args.head_source.read_text(encoding="utf-8") if args.head_source and args.head_source.is_file() else None
    head_report = args.head_report.read_text(encoding="utf-8") if args.head_report and args.head_report.is_file() else None
    for violation in attributable_violations(
        args.staged_source.read_text(encoding="utf-8"),
        args.staged_report.read_text(encoding="utf-8"),
        head_source,
        head_report,
    ):
        print(format_violation(violation))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
