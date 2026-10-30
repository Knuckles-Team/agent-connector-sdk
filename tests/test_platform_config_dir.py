"""Arbora platform config location (no legacy fallback)."""

from __future__ import annotations

import pytest

from scion_sdk import paths


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    for name in (
        "ARBORA_CONFIG_DIR",
        "AGENT_UTILITIES_CONFIG_DIR",
        "GRAPH_OS_CONFIG_DIR",
    ):
        monkeypatch.delenv(name, raising=False)


def test_env_override_wins(monkeypatch, tmp_path):
    override = tmp_path / "custom"
    monkeypatch.setenv("ARBORA_CONFIG_DIR", str(override))
    assert paths.platform_config_file("workspace.yml") == override / "workspace.yml"
    assert paths.platform_config_dir("workspace.yml") == override
    assert paths.preferred_platform_config_dir() == override


def test_xdg_path_is_arbora_only(tmp_path):
    for name in ("arbora", "agent-utilities", "graph-os"):
        (tmp_path / "xdg" / name).mkdir(parents=True)
        (tmp_path / "xdg" / name / "config.json").write_text("{}")
    assert paths.platform_config_dir() == tmp_path / "xdg" / "arbora"


def test_missing_dir_returns_arbora_path_without_creating(tmp_path):
    new = tmp_path / "xdg" / "arbora"
    assert paths.platform_config_file("workspace.yml") == new / "workspace.yml"
    assert not new.exists()


def test_old_config_settings_are_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("GRAPH_OS_CONFIG_DIR", str(tmp_path / "old"))
    monkeypatch.setenv("AGENT_UTILITIES_CONFIG_DIR", str(tmp_path / "au"))
    assert paths.platform_config_dir() == tmp_path / "xdg" / "arbora"
