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

    with pytest.raises(ImportError, match=r"scion-sdk\[a2a\]"):
        require_a2a_extra("create_a2a_app")


def test_r014_21_base_import_does_not_load_the_server_stack() -> None:
    import subprocess

    probe = (
        "import sys, agent_connector_sdk.a2a; "
        "assert 'agent_connector_sdk.a2a.app' not in sys.modules; "
        "assert 'fasta2a' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", probe], check=True)


def test_r014_21_status_parts_and_result_shapes() -> None:
    from typing import get_args

    from agent_connector_sdk.a2a import A2AResult, A2ATaskStatus, TaskState, TextPart
    from agent_connector_sdk.a2a.client import CARD_PATH

    assert A2ATaskStatus().state == "unknown"
    assert "completed" in get_args(TaskState)
    with pytest.raises(ValueError):
        A2ATaskStatus.model_validate({"state": "exploded"})
    message = A2AMessage(role="agent", parts=[TextPart(text="a"), TextPart(text="b")])
    assert message.text() == "ab" and message.parts[0].model_dump()["kind"] == "text"
    assert A2AResult(content="x").ok and not A2AResult(error="refused").ok
    assert CARD_PATH == "/.well-known/agent-card.json"


def test_r014_21_app_factory_builds_with_the_extra() -> None:
    pytest.importorskip("fasta2a")
    from agent_connector_sdk.a2a import create_a2a_app

    assert callable(create_a2a_app)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R014.21.1")
@pytest.mark.parametrize("path", ("card", "send", "poll"))
async def test_streaming_response_stops_at_bound(path: str) -> None:
    from agent_connector_sdk.a2a.client import _MAX_RESPONSE_BYTES

    class Oversized(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.chunks = 0
            self.closed = False

        async def __aiter__(self):
            for _ in range(6):
                self.chunks += 1
                yield b"x" * (_MAX_RESPONSE_BYTES // 4)

        async def aclose(self) -> None:
            self.closed = True

    stream = Oversized()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept-encoding"] == "identity"
        if path == "poll" and json.loads(request.content)["method"] == "message/send":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"id": "t", "status": {"state": "submitted"}},
                },
            )
        return httpx.Response(200, stream=stream)

    client = A2AClient(poll_interval=0.01, transport=_transport(handler))
    if path == "card":
        assert await client.fetch_card("https://peer.example") is None
    else:
        result = await client.send("https://peer.example", "hello")
        assert result.error == "A2A communication failed (ValueError)"
    assert stream.chunks == 5
    assert stream.closed


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R014.21.1")
async def test_compressed_response_is_refused_without_reading() -> None:
    class Compressed(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.read = False
            self.closed = False

        async def __aiter__(self):
            self.read = True
            yield b"secret"

        async def aclose(self) -> None:
            self.closed = True

    stream = Compressed()
    client = A2AClient(
        transport=_transport(
            lambda request: httpx.Response(
                200, headers={"Content-Encoding": "gzip"}, stream=stream
            )
        )
    )
    result = await client.send("https://peer.example", "hello")
    assert result.error == "A2A communication failed (ValueError)"
    assert not stream.read and stream.closed


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R014.21.2")
def test_a2a_app_serves_tasks_using_caller_broker_and_storage() -> None:
    import time

    from fasta2a.broker import InMemoryBroker
    from fasta2a.storage import InMemoryStorage
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel
    from starlette.testclient import TestClient

    from agent_connector_sdk.a2a import create_a2a_app

    storage = InMemoryStorage()
    broker = InMemoryBroker()
    agent = Agent(TestModel(custom_output_text="finished"))
    app = create_a2a_app(
        agent,
        name="fixture",
        url="http://testserver",
        version="1",
        storage=storage,
        broker=broker,
    )
    assert app.task_manager.storage is storage
    assert app.task_manager.broker is broker
    with TestClient(app) as client:
        card = client.get("/.well-known/agent-card.json")
        assert card.status_code == 200
        assert card.json()["name"] == "fixture"
        response = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "message/send",
                "params": {
                    "message": {
                        "kind": "message",
                        "messageId": "m1",
                        "role": "user",
                        "parts": [{"kind": "text", "text": "hello"}],
                    }
                },
            },
        )
        assert response.status_code == 200
        task_id = response.json()["result"]["id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            response = client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tasks/get",
                    "params": {"id": task_id},
                },
            )
            task = response.json()["result"]
            if task["status"]["state"] in {"completed", "failed"}:
                break
            time.sleep(0.01)
        assert task["status"]["state"] == "completed"
        assert task["history"][-1]["parts"][0]["text"] == "finished"
        assert task_id in storage.tasks
