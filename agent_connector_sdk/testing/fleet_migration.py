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

import ast
import os
from collections.abc import Callable, Iterable
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
    unscanned_files: tuple[str, ...] = ()

    @property
    def migrated(self) -> bool:
        """True when the scan is complete and found no legacy imports."""
        return not self.offending_files and not self.unscanned_files


def _imports_agent_utilities(source: str) -> bool | None:
    tree = ast.parse(source)
    import_functions = {"__import__"}
    module_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"importlib", "builtins"}:
                    module_aliases.add(alias.asname or alias.name)
        if isinstance(node, ast.ImportFrom) and node.module in {
            "importlib",
            "builtins",
        }:
            for alias in node.names:
                if alias.name in {"import_module", "__import__"}:
                    import_functions.add(alias.asname or alias.name)
    uncertain = False
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
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        dynamic = isinstance(function, ast.Name) and function.id in import_functions
        dynamic |= (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id in module_aliases
            and function.attr in {"import_module", "__import__"}
        )
        if not dynamic:
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            uncertain = True
            continue
        module = node.args[0].value
        if not isinstance(module, str) or module.startswith("."):
            uncertain = True
        elif module.split(".")[0] == "agent_utilities":
            return True
    if uncertain:
        return None
    return False


def _scan_python_sources(
    package_root: Path,
    predicate: Callable[[str], bool | None],
    *,
    exclude_dirs: frozenset[str] = _DEFAULT_EXCLUDED_DIRS,
) -> PackageScanResult:
    """Run a source predicate with fail-closed traversal and parsing."""
    offending: list[str] = []
    unscanned: list[str] = []
    scanned = 0
    if package_root.is_symlink() or not package_root.is_dir():
        return PackageScanResult(package_root.name, (), (".",))

    def traversal_error(error: OSError) -> None:
        path = Path(error.filename) if error.filename else package_root
        try:
            unscanned.append(str(path.relative_to(package_root)))
        except ValueError:
            unscanned.append(".")

    for directory, dirs, files in os.walk(package_root, onerror=traversal_error):
        base = Path(directory)
        retained: list[str] = []
        for name in sorted(dirs):
            if name in exclude_dirs:
                continue
            path = base / name
            if path.is_symlink():
                unscanned.append(str(path.relative_to(package_root)))
            else:
                retained.append(name)
        dirs[:] = retained
        for name in sorted(files):
            path = base / name
            relative = str(path.relative_to(package_root))
            if path.is_symlink():
                unscanned.append(relative)
                continue
            if not name.endswith(".py"):
                continue
            try:
                source = path.read_text(encoding="utf-8")
                legacy = predicate(source)
            except (OSError, UnicodeDecodeError, SyntaxError):
                unscanned.append(relative)
                continue
            scanned += 1
            if legacy is None:
                unscanned.append(relative)
            elif legacy:
                offending.append(relative)
    if not scanned and not unscanned:
        unscanned.append(".")
    return PackageScanResult(
        package=package_root.name,
        offending_files=tuple(sorted(offending)),
        unscanned_files=tuple(sorted(unscanned)),
    )


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
