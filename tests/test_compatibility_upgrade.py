"""Tests for the isolated public compatibility-upgrade probe."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_compatibility_upgrade import _pip_command, _source_args


@pytest.mark.spec("SCION-QUALITY-RELEASE-R005")
def test_public_upgrade_probe_uses_an_explicit_local_universe(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "public-wheelhouse"
    wheelhouse.mkdir()
    assert _source_args(wheelhouse) == [
        "--no-index",
        "--find-links",
        str(wheelhouse.resolve()),
    ]


@pytest.mark.spec("SCION-QUALITY-RELEASE-R005")
def test_public_upgrade_probe_reserves_no_deps_for_payload_repair() -> None:
    command = _pip_command(
        Path("/tmp/venv/bin/python"),
        "install",
        "--force-reinstall",
        "--no-deps",
        "scion-sdk==0.5.8",
    )
    assert command[-3:] == ["--force-reinstall", "--no-deps", "scion-sdk==0.5.8"]
    assert "--no-deps" in command


@pytest.mark.spec("SCION-QUALITY-RELEASE-R005")
def test_public_upgrade_probe_has_no_skip_result_path() -> None:
    source = Path("scripts/check_compatibility_upgrade.py").read_text(encoding="utf-8")
    assert '"skipped_checks": 0' in source
    assert "UpgradeCheckError" in source
    assert "fresh" in source and "inplace_repaired" in source
