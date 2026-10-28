"""Separate legacy OAuth keys must not share token files."""

import pytest

from agent_connector_sdk.auth.browser import FileTokenStore


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R046.9")
def test_token_store_keeps_colliding_legacy_keys_separate(tmp_path) -> None:
    store = FileTokenStore(tmp_path)
    store.set("account/a", "first")
    store.set("account_a", "second")
    assert store.get("account/a") == "first"
    assert store.get("account_a") == "second"
    assert store._path("account/a") != store._path("account_a")


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R046.9")
def test_token_store_does_not_read_ambiguous_legacy_path(tmp_path) -> None:
    (tmp_path / "account_a.json").write_text("legacy", encoding="utf-8")
    store = FileTokenStore(tmp_path)
    assert store.get("account/a") is None
    assert store.get("account_a") is None
