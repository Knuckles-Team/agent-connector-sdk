"""utilities, exceptions, config and identity."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

from agent_connector_sdk import __version__
from agent_connector_sdk.config import (
    CONFIG_FILE_SETTING,
    ConfigurationError,
    config_file_path,
    csv_values,
    load_config,
    setting,
)
from agent_connector_sdk.exceptions import (
    ApiError,
    AuthError,
    LoginRequiredError,
    MissingParameterError,
    ParameterError,
    UnauthorizedError,
    require_auth,
)
from agent_connector_sdk.identity import (
    ActorContext,
    ActorType,
    IdentityRequiredError,
    current_actor,
    use_actor,
)
from agent_connector_sdk.utilities import (
    get_logger,
    to_boolean,
    to_dict,
    to_float,
    to_integer,
    to_list,
)


def test_version_matches_installed_distribution() -> None:
    from importlib.metadata import version

    assert version("agent-connector-sdk") == __version__


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("yes", True),
        ("ON", True),
        (" 1 ", True),
        ("no", False),
        (None, False),
        (True, True),
    ],
)
def test_to_boolean(value: object, expected: bool) -> None:
    assert to_boolean(value) is expected


def test_numeric_coercions_fall_back_to_zero() -> None:
    assert to_integer("7") == 7
    assert to_integer("seven") == 0
    assert to_integer(True) == 1
    assert to_float("1.5") == 1.5
    assert to_float(None) == 0.0
    assert to_float(3) == 3.0
    assert to_float("x") == 0.0


def test_list_and_dict_coercions() -> None:
    assert to_list("a, b,,c") == ["a", "b", "c"]
    assert to_list('["x", 1]') == ["x", 1]
    assert to_list(None) == []
    assert to_dict('{"a": 1}') == {"a": 1}
    assert to_dict("") == {}
    with pytest.raises(ValueError):
        to_list(5)
    with pytest.raises(ValueError):
        to_dict("[1]")


def test_get_logger_writes_to_stderr() -> None:
    logger = get_logger("agent-connector-sdk-test")
    assert logger.level == logging.INFO
    assert any(getattr(h, "stream", None) is sys.stderr for h in logger.handlers)


def test_exception_hierarchy_is_preserved() -> None:
    assert issubclass(UnauthorizedError, AuthError)
    for error in (ApiError, MissingParameterError, ParameterError):
        with pytest.raises(error):
            raise error("boom")


def test_require_auth_refuses_without_headers() -> None:
    class Client:
        def __init__(self, headers: dict[str, str]) -> None:
            self.headers = headers

        @require_auth
        def fetch(self, item: str) -> str:
            return item

    assert Client({"Authorization": "x"}).fetch("ok") == "ok"
    with pytest.raises(LoginRequiredError):
        Client({}).fetch("denied")


def test_setting_infers_casts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SDK_INT", "12")
    monkeypatch.setenv("SDK_BOOL", "true")
    monkeypatch.setenv("SDK_BAD_INT", "twelve")
    monkeypatch.setenv("SDK_LIST", "a,b")
    assert setting("SDK_INT", 0) == 12
    assert setting("SDK_BOOL", False) is True
    assert setting("SDK_BAD_INT", 3) == 3
    assert setting("SDK_LIST", []) == ["a", "b"]
    assert setting("SDK_INT", cast=float) == 12.0
    assert setting("SDK_UNSET", "fallback") == "fallback"
    assert csv_values(" x , ,y") == ["x", "y"]


def test_config_file_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(CONFIG_FILE_SETTING, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_file_path() == tmp_path / "agent-connector-sdk" / "config.json"
    monkeypatch.setenv(CONFIG_FILE_SETTING, str(tmp_path / "explicit.json"))
    assert config_file_path() == tmp_path / "explicit.json"


def test_load_config_projects_without_overriding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    document = tmp_path / "config.json"
    document.write_text(
        json.dumps(
            {"SDK_FROM_FILE": "file", "SDK_KEEP": "file", "SDK_API_TOKEN": "env://T"}
        )
    )
    monkeypatch.setenv("SDK_KEEP", "env")
    monkeypatch.delenv("SDK_FROM_FILE", raising=False)
    monkeypatch.delenv("SDK_API_TOKEN", raising=False)
    assert load_config(document, reload=True) == document
    assert setting("SDK_FROM_FILE") == "file"
    assert setting("SDK_KEEP") == "env"
    assert load_config(tmp_path / "missing.json") is None


@pytest.mark.parametrize(
    "payload",
    ['{"SDK_PASSWORD": "plaintext"}', '{"SDK_NESTED": {"a": 1}}', "not json", "[1]"],
)
def test_load_config_rejects_invalid_documents(tmp_path: Path, payload: str) -> None:
    document = tmp_path / "config.json"
    document.write_text(payload)
    with pytest.raises(ConfigurationError):
        load_config(document, reload=True)


def test_identity_is_bound_per_context() -> None:
    with pytest.raises(IdentityRequiredError):
        current_actor()
    actor = ActorContext(
        actor_id="service:sync", actor_type=ActorType.AUTOMATED_SERVICE
    )
    with use_actor(actor):
        assert current_actor() is actor
    with pytest.raises(IdentityRequiredError):
        current_actor()
    with pytest.raises(ValueError):
        ActorContext(actor_id="", actor_type=ActorType.HUMAN)
