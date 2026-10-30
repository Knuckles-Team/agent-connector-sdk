"""Detect a connector package re-implementing SDK manifest/certify symbols.

SCION-CONNECTOR-CONTROL-R015 makes the SDK's ``manifest`` and ``certify``
packages the sole owner of connector manifest parsing, live-contract
validation, tool-schema normalization, and certification; "equivalent logic
kept in a duplicate location is retired." A package that *imports*
``ConnectorManifest``/``CertificationReport`` from ``scion_sdk`` is
fine; a package that *defines its own* top-level class or function with one
of those names is carrying a parallel schema or publisher the requirement
asks to retire.

This shares fail-closed traversal with the fleet migration import scan.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from scion_sdk.testing.fleet_migration import (
    _DEFAULT_EXCLUDED_DIRS,
    _scan_python_sources,
)

__all__ = [
    "MANIFEST_AND_CERTIFY_SURFACE_SYMBOLS",
    "DuplicateDefinitionResult",
    "scan_for_duplicate_manifest_or_certify_definitions",
]

#: The SDK's own public manifest/certify symbols (SCION-CONNECTOR-CONTROL-R015).
#: A connector package defining one of these itself, rather than importing it
#: from ``scion_sdk``, is the duplicate-location case this
#: requirement retires.
MANIFEST_AND_CERTIFY_SURFACE_SYMBOLS: frozenset[str] = frozenset(
    {"ConnectorManifest", "CertificationReport", "certify_connector"}
)


@dataclass(frozen=True)
class DuplicateDefinitionResult:
    """One connector package's duplicate-definition scan outcome."""

    package: str
    offending_files: tuple[str, ...]
    unscanned_files: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        """True when the scan is complete and finds no duplicate definitions."""
        return not self.offending_files and not self.unscanned_files


def _defines_a_tracked_symbol(source: str, symbol_names: frozenset[str]) -> bool:
    tree = ast.parse(source)
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
    result = _scan_python_sources(
        package_root,
        lambda source: _defines_a_tracked_symbol(source, symbol_names),
        exclude_dirs=exclude_dirs,
    )
    return DuplicateDefinitionResult(
        package=result.package,
        offending_files=result.offending_files,
        unscanned_files=result.unscanned_files,
    )
