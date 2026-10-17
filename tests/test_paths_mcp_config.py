"""``get_mcp_config_path`` resolves the MCP config under the connector config dir."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_connector_sdk.paths import get_mcp_config_path


def test_missing_config_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONNECTOR_CONFIG_DIR", str(tmp_path))
    assert get_mcp_config_path() is None


def test_present_config_returns_its_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONNECTOR_CONFIG_DIR", str(tmp_path))
    config = tmp_path / "mcp_config.json"
    config.write_text('{"mcpServers": {}}', encoding="utf-8")
    assert get_mcp_config_path() == str(config)
