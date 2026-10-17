"""Graph OS platform config location with the one-release legacy fallback."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from agent_connector_sdk import paths


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("GRAPH_OS_CONFIG_DIR", raising=False)
    monkeypatch.delenv("AGENT_UTILITIES_CONFIG_DIR", raising=False)
    monkeypatch.setattr(paths, "_legacy_warned", False)


def test_env_override_wins(monkeypatch, tmp_path):
    override = tmp_path / "custom"
    override.mkdir()
    (override / "workspace.yml").write_text("name: x\n")
    monkeypatch.setenv("GRAPH_OS_CONFIG_DIR", str(override))
    assert paths.platform_config_file("workspace.yml") == override / "workspace.yml"
    assert paths.platform_config_dir("workspace.yml") == override


def test_new_xdg_path(tmp_path, caplog):
    new = tmp_path / "xdg" / "graph-os"
    new.mkdir(parents=True)
    (new / "config.json").write_text("{}")
    legacy = tmp_path / "xdg" / "agent-utilities"
    legacy.mkdir(parents=True)
    (legacy / "config.json").write_text("{}")
    with caplog.at_level(logging.WARNING):
        assert paths.platform_config_dir() == new
    assert not caplog.records


def test_legacy_fallback_warns_once(monkeypatch, tmp_path, caplog):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "config.json").write_text("{}")
    (legacy / "workspace.yml").write_text("name: x\n")
    monkeypatch.setenv("AGENT_UTILITIES_CONFIG_DIR", str(legacy))
    with caplog.at_level(logging.WARNING):
        assert paths.platform_config_file("workspace.yml") == legacy / "workspace.yml"
        assert paths.platform_config_dir() == legacy
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert str(legacy) in message
    assert str(tmp_path / "xdg" / "graph-os") in message


def test_default_legacy_xdg_fallback_per_file(tmp_path, caplog):
    new = tmp_path / "xdg" / "graph-os"
    new.mkdir(parents=True)
    (new / "workspace.yml").write_text("name: x\n")
    legacy = tmp_path / "xdg" / "agent-utilities"
    legacy.mkdir(parents=True)
    (legacy / "config.json").write_text("{}")
    with caplog.at_level(logging.WARNING):
        assert paths.platform_config_file("workspace.yml") == new / "workspace.yml"
        assert paths.platform_config_dir() == legacy
    assert len(caplog.records) == 1
    assert str(legacy / "config.json") in caplog.records[0].getMessage()


def test_explicit_legacy_override_still_honoured(monkeypatch, tmp_path):
    legacy = tmp_path / "explicit"
    monkeypatch.setenv("AGENT_UTILITIES_CONFIG_DIR", str(legacy))
    assert paths.platform_config_dir() == legacy


def test_neither_present_returns_new_path_without_creating(tmp_path, caplog):
    new = tmp_path / "xdg" / "graph-os"
    with caplog.at_level(logging.WARNING):
        assert paths.platform_config_file("workspace.yml") == new / "workspace.yml"
        assert paths.platform_config_dir() == new
    assert not new.exists()
    assert not caplog.records


def test_preferred_and_legacy_directories_follow_their_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("GRAPH_OS_CONFIG_DIR", raising=False)
    monkeypatch.delenv("AGENT_UTILITIES_CONFIG_DIR", raising=False)
    assert paths.preferred_platform_config_dir() == tmp_path / "graph-os"
    assert paths.legacy_platform_config_dir() == tmp_path / "agent-utilities"
    monkeypatch.setenv("GRAPH_OS_CONFIG_DIR", str(tmp_path / "explicit"))
    assert paths.preferred_platform_config_dir() == tmp_path / "explicit"
