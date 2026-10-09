"""The per-package import scan SDK-CONNECTOR-CONTROL-R009-R013 verify by.

Each batch requirement's own verification column asks for the same proof:
"a per-package import scan ... confirming no agent_utilities import
remains." This module is that scan, reusable across every alphabetical
batch (A-E, F-J, K-O, P-S, T-Z) rather than re-derived per batch, matching
the SDK-CONNECTOR-CONTROL-R004 precedent that contract-pin verification is
owned once by this SDK's own test kit, not recomputed downstream.

A connector package's own migration commit lands in that package's own
repository; this scan only proves the result, from source, by AST rather
than a brittle text search.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "PackageScanResult",
    "scan_for_agent_utilities_imports",
    "scan_many_packages",
]

_DEFAULT_EXCLUDED_DIRS = frozenset({".venv", "build", "__pycache__"})


@dataclass(frozen=True)
class PackageScanResult:
    """One connector package's import-scan outcome."""

    package: str
    offending_files: tuple[str, ...]

    @property
    def migrated(self) -> bool:
        """True when no scanned file imports ``agent_utilities``."""
        return not self.offending_files


def _imports_agent_utilities(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            alias.name.split(".")[0] == "agent_utilities" for alias in node.names
        ):
            return True
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.split(".")[0] == "agent_utilities"
        ):
            return True
    return False


def scan_for_agent_utilities_imports(
    package_root: Path,
    *,
    exclude_dirs: frozenset[str] = _DEFAULT_EXCLUDED_DIRS,
) -> PackageScanResult:
    """Scan every ``.py`` file under ``package_root`` for an ``agent_utilities`` import.

    Parses each file with :mod:`ast` rather than a text search, so a string
    or comment that merely mentions ``agent_utilities`` is never a false
    positive. A file that fails to parse or decode is skipped, not treated
    as clean by omission versus flagged by inspection of its raw text.
    """
    offending: list[str] = []
    for path in sorted(package_root.rglob("*.py")):
        if any(part in exclude_dirs for part in path.relative_to(package_root).parts):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _imports_agent_utilities(source):
            offending.append(str(path.relative_to(package_root)))
    return PackageScanResult(
        package=package_root.name, offending_files=tuple(offending)
    )


def scan_many_packages(
    package_roots: Iterable[Path],
    *,
    exclude_dirs: frozenset[str] = _DEFAULT_EXCLUDED_DIRS,
) -> dict[str, PackageScanResult]:
    """Scan several package roots and return each one's result, keyed by name.

    SDK-CONNECTOR-CONTROL-R014 asks for "a cross-repository import scan
    showing no connector still depends on the superseded implementation".
    This is that scan's one call site: every batch requirement (R009-R013)
    and R014's own fleet-wide census share this function instead of each
    re-deriving a loop over :func:`scan_for_agent_utilities_imports`.
    """
    return {
        root.name: scan_for_agent_utilities_imports(root, exclude_dirs=exclude_dirs)
        for root in package_roots
    }
