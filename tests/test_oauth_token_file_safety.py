"""Legacy OAuth token files must not follow a final-component symlink."""

import stat

import pytest

from agent_connector_sdk.auth.browser import FileTokenStore


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R046.8")
def test_token_file_symlink_never_reads_or_overwrites_target(tmp_path) -> None:
    root = tmp_path / "tokens"
    root.mkdir()
    target = tmp_path / "outside"
    target.write_text("original", encoding="utf-8")
    (root / "account.json").symlink_to(target)
    store = FileTokenStore(root)
    assert store.get("account") is None
    with pytest.raises(OSError):
        store.set("account", "replacement")
    assert target.read_text(encoding="utf-8") == "original"


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R046.8")
def test_token_file_is_restricted_before_write(tmp_path) -> None:
    root = tmp_path / "tokens"
    root.mkdir()
    path = root / "account.json"
    path.write_text("old", encoding="utf-8")
    path.chmod(0o666)
    store = FileTokenStore(root)
    store.set("account", "new")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert store.get("account") == "new"


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R046.8")
def test_token_store_refuses_nonregular_files_without_waiting(tmp_path) -> None:
    import os

    root = tmp_path / "tokens"
    root.mkdir()
    os.mkfifo(root / "account.json")
    store = FileTokenStore(root)
    assert store.get("account") is None
    with pytest.raises(OSError):
        store.set("account", "new")
