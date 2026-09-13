"""Concurrency, action dispatch and context helpers."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from agent_connector_sdk.mcp.action_dispatch import (
    DISCOVERY_ACTIONS,
    canonicalize,
    dispatch,
    dispatch_async,
    is_destructive_action,
    parse_json_object,
    public_actions,
    resolve_action,
    suggest,
    unknown_action_error,
)
from agent_connector_sdk.mcp.concurrency import (
    fold_body_arguments,
    invoke_client_method,
    run_blocking,
)
from agent_connector_sdk.mcp.context import ctx_confirm_destructive, ctx_log


class Client:
    def get_movie(self, movie_id: int) -> dict[str, int]:
        return {"id": movie_id}

    def create_item(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        return {"project_id": project_id, "data": data}

    async def delete_item(self, item_id: str) -> str:
        return item_id


class Elicitation:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome

    async def elicit(self, message: str, response_type: type) -> object:
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def test_fold_body_arguments() -> None:
    folded = fold_body_arguments(
        Client().create_item, (), {"project_id": "p", "name": "n"}
    )
    assert folded == {"project_id": "p", "data": {"name": "n"}}
    unchanged = {"movie_id": 1}
    assert fold_body_arguments(Client().get_movie, (), unchanged) is unchanged
    assert fold_body_arguments(len, (), {"x": 1}) == {"x": 1}


async def test_run_blocking_and_invoke_client_method() -> None:
    assert await run_blocking(Client().get_movie, 3) == {"id": 3}
    with pytest.raises(TypeError):
        await run_blocking(Client().delete_item, "x")
    with pytest.raises(TypeError):
        await run_blocking(lambda: Client().delete_item("x"))
    assert await invoke_client_method(Client().delete_item, "gone") == "gone"
    result = await invoke_client_method(Client().create_item, project_id="p", title="t")
    assert result == {"project_id": "p", "data": {"title": "t"}}


def test_parse_json_object_is_bounded() -> None:
    assert parse_json_object('{"a": 1}') == {"a": 1}
    assert parse_json_object(None) == {}
    assert parse_json_object("  ") == {}
    for bad in ("[1]", "{", "x" * 70_000):
        with pytest.raises(ValueError):
            parse_json_object(bad)


def test_action_resolution() -> None:
    names = public_actions(Client())
    assert names == ["create_item", "delete_item", "get_movie"]
    assert canonicalize("get_movies", names) == "get_movie"
    assert canonicalize("fetch", names, aliases={"fetch": "get_movie"}) == "get_movie"
    assert canonicalize("unknown", names) is None
    assert suggest("get_movi", names) == ["get_movie"]
    assert "Did you mean" in str(unknown_action_error("get_movi", names, target="svc"))
    assert resolve_action(DISCOVERY_ACTIONS[0], names, service="svc") == {
        "service": "svc",
        "actions": names,
    }
    assert resolve_action("get_movies", names) == "get_movie"
    with pytest.raises(ValueError):
        resolve_action("nope", names)
    assert is_destructive_action("delete_item")
    assert not is_destructive_action("delete_item", {"destructive": False})
    assert is_destructive_action("purge", {"http": "DELETE"})


async def test_dispatch_shapes() -> None:
    client = Client()
    assert dispatch(client, "get_movies", {"movie_id": 1}) == {"id": 1}
    assert dispatch(client, "help")["actions"] == public_actions(client)
    assert (
        dispatch(client, "get_movie", {"movie_id": 2}, result_coercer=lambda r: r["id"])
        == 2
    )
    with pytest.raises(ValueError):
        dispatch(client, "nothing")
    cancelled = await dispatch_async(client, "delete_item", {"item_id": "x"})
    assert cancelled == {"cancelled": True, "operation": "delete_item"}
    accepted = Elicitation(SimpleNamespace(action="accept", data=True))
    assert (
        await dispatch_async(client, "delete_item", {"item_id": "x"}, ctx=accepted)
        == "x"
    )

    async def coerce(value: str) -> str:
        return value.upper()

    assert (
        await dispatch_async(
            client, "delete_item", {"item_id": "x"}, ctx=accepted, result_coercer=coerce
        )
        == "X"
    )
    assert (await dispatch_async(client, "list_actions"))["service"] == "Client"
    with pytest.raises(ValueError):
        await dispatch_async(client, "nothing")


async def test_ctx_confirm_destructive_fails_closed() -> None:
    assert not await ctx_confirm_destructive(None, "drop")
    assert not await ctx_confirm_destructive(
        Elicitation(RuntimeError("no client")), "drop"
    )
    assert not await ctx_confirm_destructive(
        Elicitation(SimpleNamespace(action="decline", data=True)), "drop"
    )
    assert await ctx_confirm_destructive(
        Elicitation(SimpleNamespace(action="accept", data=True)), "drop"
    )


async def test_ctx_log(caplog: pytest.LogCaptureFixture) -> None:
    delivered: list[str] = []

    class Context:
        async def warning(self, message: str) -> None:
            delivered.append(message)

        async def info(self, message: str) -> None:
            raise RuntimeError("client gone")

    logger = logging.getLogger("ctx-log-test")
    with caplog.at_level(logging.DEBUG, logger="ctx-log-test"):
        await ctx_log(Context(), "careful", logger=logger, level="warning")
        await ctx_log(Context(), "hello", logger=logger)
        await ctx_log(None, "quiet", logger=logger)
    assert delivered == ["careful"]
    assert "client log delivery failed" in caplog.text
    with pytest.raises(ValueError):
        await ctx_log(None, "x", logger=logger, level="critical")
