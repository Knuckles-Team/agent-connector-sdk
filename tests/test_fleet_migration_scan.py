"""The batch-migration import scan: AST-based, not a brittle text search."""

from __future__ import annotations

from pathlib import Path

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
