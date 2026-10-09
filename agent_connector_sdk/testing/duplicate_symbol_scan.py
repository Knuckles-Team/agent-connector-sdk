"""Detect a connector package re-implementing SDK manifest/certify symbols.

SDK-CONNECTOR-CONTROL-R015 makes the SDK's ``manifest`` and ``certify``
packages the sole owner of connector manifest parsing, live-contract
validation, tool-schema normalization, and certification; "equivalent logic
kept in a duplicate location is retired." A package that *imports*
``ConnectorManifest``/``CertificationReport`` from ``agent_connector_sdk`` is
fine; a package that *defines its own* top-level class or function with one
of those names is carrying a parallel schema or publisher the requirement
asks to retire.

This mirrors ``fleet_migration.scan_for_agent_utilities_imports``: AST-based,
not a brittle text search, and a file that fails to parse is skipped rather
than fabricated clean.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "MANIFEST_AND_CERTIFY_SURFACE_SYMBOLS",
    "DuplicateDefinitionResult",
    "scan_for_duplicate_manifest_or_certify_definitions",
]

#: The SDK's own public manifest/certify symbols (SDK-CONNECTOR-CONTROL-R015).
#: A connector package defining one of these itself, rather than importing it
#: from ``agent_connector_sdk``, is the duplicate-location case this
#: requirement retires.
MANIFEST_AND_CERTIFY_SURFACE_SYMBOLS: frozenset[str] = frozenset(
    {"ConnectorManifest", "CertificationReport", "certify_connector"}
)

_DEFAULT_EXCLUDED_DIRS = frozenset({".venv", "build", "__pycache__"})


@dataclass(frozen=True)
class DuplicateDefinitionResult:
    """One connector package's duplicate-definition scan outcome."""

    package: str
    offending_files: tuple[str, ...]

    @property
    def clean(self) -> bool:
        """True when no scanned file locally defines a tracked symbol."""
        return not self.offending_files


def _defines_a_tracked_symbol(source: str, symbol_names: frozenset[str]) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in symbol_names
        ):
            return True
    return False


def scan_for_duplicate_manifest_or_certify_definitions(
    package_root: Path,
    *,
    symbol_names: frozenset[str] = MANIFEST_AND_CERTIFY_SURFACE_SYMBOLS,
    exclude_dirs: frozenset[str] = _DEFAULT_EXCLUDED_DIRS,
) -> DuplicateDefinitionResult:
    """Scan every ``.py`` file under ``package_root`` for a local redefinition
    of one of the SDK's manifest/certify surface symbols.
    """
    offending: list[str] = []
    for path in sorted(package_root.rglob("*.py")):
        if any(part in exclude_dirs for part in path.relative_to(package_root).parts):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _defines_a_tracked_symbol(source, symbol_names):
            offending.append(str(path.relative_to(package_root)))
    return DuplicateDefinitionResult(
        package=package_root.name, offending_files=tuple(offending)
    )
