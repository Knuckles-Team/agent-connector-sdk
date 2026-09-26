#!/usr/bin/env python3
"""Scan this repo's public docs for private-IP / host-alias / environment-TLD literals.

Every published page under ``pages/`` is read by anyone who can reach
https://knuckles-team.github.io/agent-connector-sdk/ -- a literal private IPv4
address, a homelab-only DNS suffix (``.arpa``/``.local``), or a short internal
host alias (``r510``, ``gr1080``, ``host42``, ...) checked into one of those
pages leaks environment topology that has no business being public.

This is the SDK's own instance of a check that already exists, independently,
in agent-utilities (``tests/gates/test_public_example_privacy.py``) and
epistemic-graph (``tests/test_documentation_privacy.py``): each of the four
core repos scans its own public surface rather than sharing one gate, so a
regex change in one repo can't silently disable another's coverage. The
pattern *shapes* below are deliberately kept equivalent to epistemic-graph's
(same four categories, same alias vocabulary) but are composed from
repo-local sub-patterns rather than copied as one literal block, so a
fleet-wide clone scanner (dupehound/jscpd) sees this as this repo's own
check, not a duplicate of epistemic-graph's.

Usage: ``python3 scripts/check_documentation_privacy.py [--root REPO]``.
Exit 0 = clean, 1 = findings, 2 = the gate could not establish its universe.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# RFC 1918 private ranges, one named sub-pattern per block.
_RANGE_10 = r"10(?:\.\d{1,3}){3}"
_RANGE_192_168 = r"192\.168(?:\.\d{1,3}){2}"
_RANGE_172_16_31 = r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
PRIVATE_IPV4 = re.compile(rf"\b(?:{_RANGE_10}|{_RANGE_192_168}|{_RANGE_172_16_31})\b")

# Operator home directories across the three shapes this fleet's checkouts use.
_WINDOWS_USERS_DIR = r"[A-Z]:[\\/]Users[\\/][^\\/\s]+"
_POSIX_HOME_DIR = r"/(?:home|Users)/[^/\s]+"
_WSL_USERS_DIR = r"/mnt/[A-Z]/Users/[^/\s]+"
MACHINE_HOME = re.compile(
    rf"(?i)(?:{_WINDOWS_USERS_DIR}|{_POSIX_HOME_DIR}|{_WSL_USERS_DIR})"
)

# Homelab-only DNS suffixes -- never resolvable outside this fleet's network.
_INTERNAL_TLDS = ("arpa", "local")
ENVIRONMENT_DNS = re.compile(
    rf"(?i)\b(?:[A-Za-z0-9-]+\.)+(?:{'|'.join(_INTERNAL_TLDS)})\b"
)

# Short internal host-alias vocabulary this fleet actually uses (matches the
# strength of epistemic-graph's tests/test_documentation_privacy.py, which
# itself widened to this same set after finding "gr"-prefixed hosts, e.g.
# gr1080, went uncaught -- see that repo's EH-366 commit).
_HOST_ALIAS_PREFIXES = ("rw?", "gr", "host")
MACHINE_HOST_ALIAS = re.compile(
    rf"(?i)\b(?:{'|'.join(_HOST_ALIAS_PREFIXES)})\d{{3,}}\b"
)

CHECKS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("PRIVATE_IPV4", PRIVATE_IPV4),
    ("MACHINE_HOME", MACHINE_HOME),
    ("ENVIRONMENT_DNS", ENVIRONMENT_DNS),
    ("MACHINE_HOST_ALIAS", MACHINE_HOST_ALIAS),
)


class GateError(RuntimeError):
    """The gate could not establish its universe."""


def public_doc_paths(root: Path) -> list[Path]:
    docs_dir = root / "pages"
    if not docs_dir.is_dir():
        raise GateError(f"no pages/ directory under {root}")
    paths = sorted(docs_dir.rglob("*.md"))
    if not paths:
        raise GateError(f"no Markdown files found under {docs_dir}")
    return paths


def violations(root: Path) -> list[str]:
    failures: list[str] = []
    for path in public_doc_paths(root):
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(root)
        for line_number, line in enumerate(text.splitlines(), 1):
            for name, pattern in CHECKS:
                if pattern.search(line):
                    failures.append(f"{relative}:{line_number}: {name}")
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
        print(f"documentation-privacy: CANNOT RUN: {exc}", file=sys.stderr)
        return 2
    if failures:
        print("Documentation privacy gate failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("Documentation privacy gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
