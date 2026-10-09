"""SDK-CONNECTOR-CONTROL-R015.1: detect a locally re-implemented manifest/certify symbol."""

from __future__ import annotations

from pathlib import Path

from agent_connector_sdk.testing.duplicate_symbol_scan import (
    DuplicateDefinitionResult,
    scan_for_duplicate_manifest_or_certify_definitions,
)


def _write(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_a_package_importing_the_sdk_symbol_is_clean(tmp_path: Path) -> None:
    _write(
        tmp_path / "clean_pkg" / "server.py",
        "from agent_connector_sdk.manifest import ConnectorManifest\n",
    )

    result = scan_for_duplicate_manifest_or_certify_definitions(tmp_path / "clean_pkg")

    assert isinstance(result, DuplicateDefinitionResult)
    assert result.clean
    assert result.offending_files == ()


def test_a_locally_defined_class_is_caught(tmp_path: Path) -> None:
    _write(
        tmp_path / "legacy_pkg" / "schema.py",
        "class ConnectorManifest:\n    pass\n",
    )

    result = scan_for_duplicate_manifest_or_certify_definitions(tmp_path / "legacy_pkg")

    assert not result.clean
    assert result.offending_files == ("schema.py",)


def test_a_locally_defined_function_is_caught(tmp_path: Path) -> None:
    _write(
        tmp_path / "legacy_pkg" / "publisher.py",
        "def certify_connector(checkout):\n    ...\n",
    )

    result = scan_for_duplicate_manifest_or_certify_definitions(tmp_path / "legacy_pkg")

    assert not result.clean
    assert result.offending_files == ("publisher.py",)


def test_a_mention_in_a_string_or_comment_is_not_a_false_positive(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "clean_pkg" / "docs.py",
        '"""See ConnectorManifest in the SDK docs."""\n',
    )

    result = scan_for_duplicate_manifest_or_certify_definitions(tmp_path / "clean_pkg")

    assert result.clean


def test_a_file_that_fails_to_parse_is_skipped_not_fabricated_clean(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "pkg" / "broken.py", "def broken(:\n")

    result = scan_for_duplicate_manifest_or_certify_definitions(tmp_path / "pkg")

    assert result.offending_files == ()
