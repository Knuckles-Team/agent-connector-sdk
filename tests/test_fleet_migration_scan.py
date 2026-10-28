"""The batch-migration import scan: AST-based, not a brittle text search."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from agent_connector_sdk.testing import fleet_migration
from agent_connector_sdk.testing.fleet_migration import (
    PackageScanResult,
    scan_for_agent_utilities_imports,
    scan_many_packages,
)


def _write(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_a_clean_package_is_reported_migrated(tmp_path: Path) -> None:
    _write(
        tmp_path / "clean_pkg" / "server.py",
        "from agent_connector_sdk.mcp.server import build_server\n",
    )

    result = scan_for_agent_utilities_imports(tmp_path / "clean_pkg")

    assert isinstance(result, PackageScanResult)
    assert result.migrated
    assert result.offending_files == ()


def test_a_plain_import_is_caught(tmp_path: Path) -> None:
    _write(tmp_path / "legacy_pkg" / "a.py", "import agent_utilities.core.config\n")

    result = scan_for_agent_utilities_imports(tmp_path / "legacy_pkg")

    assert not result.migrated
    assert result.offending_files == ("a.py",)


def test_a_from_import_is_caught(tmp_path: Path) -> None:
    _write(
        tmp_path / "legacy_pkg" / "b.py",
        "from agent_utilities.mcp.verbose_tools import register_tool_surface\n",
    )

    result = scan_for_agent_utilities_imports(tmp_path / "legacy_pkg")

    assert not result.migrated
    assert result.offending_files == ("b.py",)


def test_a_mention_in_a_string_or_comment_is_not_a_false_positive(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "clean_pkg" / "docs.py",
        '# migrated off agent_utilities\n"""See agent_utilities for history."""\n',
    )

    result = scan_for_agent_utilities_imports(tmp_path / "clean_pkg")

    assert result.migrated


def test_excluded_directories_are_not_scanned(tmp_path: Path) -> None:
    _write(
        tmp_path / "pkg" / ".venv" / "site" / "x.py",
        "import agent_utilities\n",
    )
    _write(tmp_path / "pkg" / "real.py", "import httpx\n")

    result = scan_for_agent_utilities_imports(tmp_path / "pkg")

    assert result.migrated


def test_a_file_that_fails_to_parse_is_skipped_not_fabricated_clean(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "pkg" / "broken.py", "def broken(:\n")

    result = scan_for_agent_utilities_imports(tmp_path / "pkg")

    assert result.offending_files == ()
    assert result.unscanned_files == ("broken.py",)
    assert not result.migrated


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R014.28")
def test_incomplete_or_ambiguous_fleet_scans_never_prove_migration(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    missing = tmp_path / "missing"
    assert not scan_for_agent_utilities_imports(empty).migrated
    assert not scan_for_agent_utilities_imports(missing).migrated

    root = tmp_path / "pkg"
    _write(root / "good.py", "import httpx\n")
    (root / "invalid.py").write_bytes(b"\xff")
    (root / "linked.py").symlink_to(root / "good.py")
    target = tmp_path / "target"
    target.mkdir()
    (root / "linked_dir").symlink_to(target, target_is_directory=True)
    result = scan_for_agent_utilities_imports(root)
    assert not result.migrated
    assert result.unscanned_files == ("invalid.py", "linked.py", "linked_dir")

    other = tmp_path / "other" / "pkg"
    _write(other / "good.py", "import httpx\n")
    with pytest.raises(ValueError, match="unique"):
        scan_many_packages([root, other])


def test_traversal_error_prevents_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "pkg"
    _write(root / "good.py", "import httpx\n")

    def broken_walk(
        path: Path, *, onerror: Callable[[OSError], None]
    ) -> Iterator[tuple[str, list[str], list[str]]]:
        assert path == root
        onerror(PermissionError(13, "denied", str(root / "private")))
        yield str(root), [], ["good.py"]

    monkeypatch.setattr(fleet_migration.os, "walk", broken_walk)
    result = scan_for_agent_utilities_imports(root)
    assert result.unscanned_files == ("private",)
    assert not result.migrated


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R014.1")
def test_scan_many_packages_reports_each_root_by_name(tmp_path: Path) -> None:
    """SDK-CONNECTOR-CONTROL-R014.1: one call site scans a whole fleet of
    connector package roots and keys each result by package name, so a
    cross-repository census is one function call, not a hand-rolled loop."""
    _write(
        tmp_path / "clean_pkg" / "server.py",
        "from agent_connector_sdk.mcp.server import build_server\n",
    )
    _write(tmp_path / "legacy_pkg" / "a.py", "import agent_utilities.core.config\n")

    results = scan_many_packages([tmp_path / "clean_pkg", tmp_path / "legacy_pkg"])

    assert set(results) == {"clean_pkg", "legacy_pkg"}
    assert results["clean_pkg"].migrated
    assert not results["legacy_pkg"].migrated
    assert results["legacy_pkg"].offending_files == ("a.py",)
