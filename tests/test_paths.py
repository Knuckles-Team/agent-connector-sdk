"""Per-connector XDG directories."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_connector_sdk.paths import cache_dir, config_dir, data_dir


def test_xdg_bases_and_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.delenv("AUDIO_TRANSCRIBER_DATA_DIR", raising=False)
    assert data_dir("audio-transcriber") == tmp_path / "data" / "audio-transcriber"
    assert cache_dir("demo") == Path.home() / ".cache" / "demo"
    monkeypatch.setenv("DEMO_MCP_CONFIG_DIR", str(tmp_path / "cfg"))
    assert config_dir("demo-mcp") == tmp_path / "cfg"


@pytest.mark.parametrize("bad", ["", "a/b", "..", " "])
def test_connector_name_must_be_a_plain_directory(bad: str) -> None:
    with pytest.raises(ValueError, match="plain directory"):
        data_dir(bad)
