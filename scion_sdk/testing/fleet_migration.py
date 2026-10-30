"""The per-package import scan SCION-CONNECTOR-CONTROL-R009-R013 verify by.

Each batch requirement's own verification column asks for the same proof:
"a per-package import scan ... confirming no agent_utilities import
remains." This module is that scan, reusable across every alphabetical
batch (A-E, F-J, K-O, P-S, T-Z) rather than re-derived per batch, matching
the SCION-CONNECTOR-CONTROL-R004 precedent that contract-pin verification is
owned once by this SDK's own test kit, not recomputed downstream.

A connector package's own migration commit lands in that package's own
repository; this scan only proves the result, from source, by AST rather
than a brittle text search.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from scion_sdk.testing._fleet_scan import _imports_agent_utilities
from scion_sdk.testing._fleet_walk import (
    _DEFAULT_EXCLUDED_DIRS,
    PackageScanResult,
    _scan_python_sources,
)

__all__ = [
    "JsonTagLoaderEntry",
    "OperationMapping",
    "PackageScanResult",
    "loader_parity_problems",
    "scan_for_agent_utilities_imports",
    "scan_many_packages",
]

_REGISTRATION_KINDS = frozenset({"operation", "callback", "action_dispatch"})


def scan_for_agent_utilities_imports(
    package_root: Path,
    *,
    exclude_dirs: frozenset[str] = _DEFAULT_EXCLUDED_DIRS,
) -> PackageScanResult:
    """Scan Python imports without treating incomplete scans as migrated."""
    return _scan_python_sources(
        package_root, _imports_agent_utilities, exclude_dirs=exclude_dirs
    )


def scan_many_packages(
    package_roots: Iterable[Path],
    *,
    exclude_dirs: frozenset[str] = _DEFAULT_EXCLUDED_DIRS,
) -> dict[str, PackageScanResult]:
    """Scan several package roots and return each one's result, keyed by name.

    SCION-CONNECTOR-CONTROL-R014 asks for "a cross-repository import scan
    showing no connector still depends on the superseded implementation".
    This is that scan's one call site: every batch requirement (R009-R013)
    and R014's own fleet-wide census share this function instead of each
    re-deriving a loop over :func:`scan_for_agent_utilities_imports`.
    """
    results: dict[str, PackageScanResult] = {}
    for root in package_roots:
        if root.name in results:
            raise ValueError("connector package names must be unique")
        results[root.name] = scan_for_agent_utilities_imports(
            root, exclude_dirs=exclude_dirs
        )
    return results


@dataclass(frozen=True)
class OperationMapping:
    """One source-to-target operation binding with the facts that must match."""

    source_operation_id: str
    target_operation_id: str
    source_input_schema: str
    target_input_schema: str
    source_output_schema: str
    target_output_schema: str
    source_tags: frozenset[str] = frozenset()
    target_tags: frozenset[str] = frozenset()
    source_authorization: str = ""
    target_authorization: str = ""


@dataclass(frozen=True)
class JsonTagLoaderEntry:
    """SCION-CONNECTOR-CONTROL-R020.1: one JSON tag loader and its target mapping."""

    package: str
    source_revision: str
    loader_path: str
    json_path: str
    json_digest: str
    registration: str
    mappings: tuple[OperationMapping, ...] = ()


def loader_parity_problems(
    entries: Iterable[JsonTagLoaderEntry], inventory: Iterable[tuple[str, str]]
) -> list[str]:
    """Return every reason the loader inventory cannot gate a replacement.

    ``inventory`` lists the ``(package, loader_path)`` pairs found by a scan.
    An empty result means complete and schema, tag and authorization parity.
    """
    problems: list[str] = []
    entries = list(entries)
    seen = {(e.package, e.loader_path) for e in entries}
    for pair in sorted(set(inventory) - seen):
        problems.append(f"loader not inventoried: {pair[0]}:{pair[1]}")
    for entry in entries:
        problems.extend(_entry_problems(entry))
    return problems


def _entry_problems(entry: JsonTagLoaderEntry) -> list[str]:
    where = f"{entry.package}:{entry.loader_path}"
    problems: list[str] = []
    if entry.registration not in _REGISTRATION_KINDS:
        problems.append(f"{where}: unknown registration {entry.registration!r}")
    if not (entry.source_revision and entry.json_digest and entry.json_path):
        problems.append(f"{where}: incomplete entry")
    if not entry.mappings:
        problems.append(f"{where}: no operation mapping")
    for m in entry.mappings:
        problems.extend(
            _mapping_problems(
                f"{where}: {m.source_operation_id}->{m.target_operation_id}", m
            )
        )
    return problems


_MAPPING_FACETS = (
    ("source_input_schema", "target_input_schema", "input schema differs"),
    ("source_output_schema", "target_output_schema", "output schema differs"),
    ("source_tags", "target_tags", "tags differ"),
    ("source_authorization", "target_authorization", "authorization differs"),
)


def _mapping_problems(op: str, m: OperationMapping) -> list[str]:
    return [
        f"{op}: {message}"
        for source, target, message in _MAPPING_FACETS
        if getattr(m, source) != getattr(m, target)
    ]
