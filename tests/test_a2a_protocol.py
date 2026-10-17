"""SDK-CONNECTOR-CONTROL-R014.21: the reusable A2A protocol pieces."""

from __future__ import annotations

import builtins
import json
import sys

import httpx
import pytest

from agent_connector_sdk.a2a import (
    A2AClient,
    A2AMessage,
    A2ATask,
    AgentCard,
    AgentSkill,
)


def _transport(handler):
    return httpx.MockTransport(handler)


def test_r014_21_card_round_trips_the_wire_aliases() -> None:
    card = AgentCard(
        name="peer",
        url="https://peer.example.test",
        skills=[AgentSkill(id="s", name="Search", tags=["search"])],
    )
    wire = card.wire()
    assert wire["defaultInputModes"] == ["text"]
    assert wire["skills"][0]["inputModes"] == ["text"]
    assert AgentCard.model_validate(wire) == card


def test_r014_21_task_reports_the_last_agent_reply() -> None:
    task = A2ATask.model_validate(
        {
            "id": "t1",
            "status": {"state": "completed"},
            "history": [
                A2AMessage.user_text("hi").wire(),
                {"role": "agent", "parts": [{"kind": "text", "text": "hello"}]},
            ],
        }
    )
    assert not task.pending
    assert task.last_agent_message().text() == "hello"


@pytest.mark.asyncio
async def test_r014_21_client_sends_then_polls_until_completed() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body["method"])
        if body["method"] == "message/send":
            result = {"id": "t1", "status": {"state": "submitted"}}
        else:
            result = {
                "id": "t1",
                "status": {"state": "completed"},
                "history": [
                    {"role": "agent", "parts": [{"kind": "text", "text": "done"}]}
                ],
            }
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    client = A2AClient(poll_interval=0.01, transport=_transport(handler))
    result = await client.send("https://peer.example.test/", "do it")
    assert result.ok and result.content == "done"
    assert calls == ["message/send", "tasks/get"]


@pytest.mark.asyncio
async def test_r014_21_client_never_echoes_a_remote_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": 1, "error": {"message": "secret"}}
        )

    result = await A2AClient(transport=_transport(handler)).send("https://p", "x")
    assert result.error == "A2A peer rejected the request"
    assert "secret" not in str(result)


@pytest.mark.asyncio
async def test_r014_21_fetch_card_rejects_an_invalid_card() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/.well-known/agent-card.json"
        return httpx.Response(200, json={"name": ""})

    assert (
        await A2AClient(transport=_transport(handler)).fetch_card("https://p") is None
    )


def test_r014_21_app_factory_names_the_a2a_extra(monkeypatch) -> None:
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.split(".")[0] in {"fasta2a", "starlette"}:
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "fasta2a", raising=False)
    monkeypatch.setattr(builtins, "__import__", blocked)
    from agent_connector_sdk.a2a.app import require_a2a_extra

    with pytest.raises(ImportError, match=r"agent-connector-sdk\[a2a\]"):
        require_a2a_extra("create_a2a_app")


def test_r014_21_base_import_does_not_load_the_server_stack() -> None:
    import subprocess

    probe = (
        "import sys, agent_connector_sdk.a2a; "
        "assert 'agent_connector_sdk.a2a.app' not in sys.modules; "
        "assert 'fasta2a' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", probe], check=True)
