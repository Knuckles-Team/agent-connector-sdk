"""Fail-closed source-tree traversal for the fleet import scan."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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


def _relative_or_root(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return "."


def _retained_dirs(
    base: Path,
    dirs: list[str],
    *,
    root: Path,
    exclude: frozenset[str],
    unscanned: list[str],
) -> list[str]:
    retained: list[str] = []
    for name in sorted(dirs):
        if name in exclude:
            continue
        path = base / name
        if path.is_symlink():
            unscanned.append(str(path.relative_to(root)))
        else:
            retained.append(name)
    return retained


def _scan_file(
    path: Path, predicate: Callable[[str], bool | None]
) -> bool | str | None:
    """Return the predicate verdict, or ``"unscanned"`` when unreadable."""
    try:
        return predicate(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return "unscanned"


def _file_outcome(
    path: Path, relative: str, predicate: Callable[[str], bool | None]
) -> str:
    """One of ``skip``, ``unscanned``, ``offending`` or ``clean``."""
    if path.is_symlink():
        return "unscanned"
    if not relative.endswith(".py"):
        return "skip"
    verdict = _scan_file(path, predicate)
    if verdict == "unscanned" or verdict is None:
        return "unscanned"
    return "offending" if verdict else "clean"


def _scan_files(
    base: Path,
    files: list[str],
    *,
    root: Path,
    predicate: Callable[[str], bool | None],
) -> tuple[list[str], list[str], int]:
    """Return ``(offending, unscanned, scanned)`` for one directory's files."""
    outcomes: dict[str, list[str]] = {
        "skip": [],
        "unscanned": [],
        "offending": [],
        "clean": [],
    }
    for name in sorted(files):
        path = base / name
        relative = str(path.relative_to(root))
        outcomes[_file_outcome(path, relative, predicate)].append(relative)
    return (
        outcomes["offending"],
        outcomes["unscanned"],
        len(outcomes["offending"]) + len(outcomes["clean"]),
    )


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
        unscanned.append(_relative_or_root(path, package_root))

    for directory, dirs, files in os.walk(package_root, onerror=traversal_error):
        base = Path(directory)
        dirs[:] = _retained_dirs(
            base, dirs, root=package_root, exclude=exclude_dirs, unscanned=unscanned
        )
        found, missed, count = _scan_files(
            base, files, root=package_root, predicate=predicate
        )
        offending += found
        unscanned += missed
        scanned += count
    if not scanned and not unscanned:
        unscanned.append(".")
    return PackageScanResult(
        package=package_root.name,
        offending_files=tuple(sorted(offending)),
        unscanned_files=tuple(sorted(unscanned)),
    )
