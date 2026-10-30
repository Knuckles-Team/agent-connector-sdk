"""Bounded JSON-RPC client for one A2A exchange.

CONCEPT:SCION-CONNECTOR-CONTROL-R014.21

``message/send`` then ``tasks/get`` polling until the task leaves a pending
state or the deadline passes. Failures come back as an :class:`A2AResult` with
a fixed message; remote error bodies are never echoed. Card and RPC responses
use identity encoding and are read incrementally under a 4 MiB limit.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import ValidationError

from .models import A2AMessage, A2ATask, AgentCard

CARD_PATH = "/.well-known/agent-card.json"
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


def _validate_rpc_response(data: Any, request_id: int) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("jsonrpc") != "2.0":
        raise ValueError("A2A response envelope is invalid")
    response_id = data.get("id")
    if not isinstance(response_id, int) or isinstance(response_id, bool):
        raise ValueError("A2A response id is invalid")
    if response_id != request_id or (("result" in data) == ("error" in data)):
        raise ValueError("A2A response does not match its request")
    if "error" in data and not isinstance(data["error"], dict):
        raise ValueError("A2A response error is invalid")
    return data


def _matching_task(data: Any, task_id: str) -> A2ATask:
    task = A2ATask.model_validate(data)
    if task.id != task_id:
        raise ValueError("A2A poll returned another task")
    return task


class _PeerRejected(Exception):
    """A peer rejected a request without exposing its error body."""


@dataclass(frozen=True)
class A2AResult:
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class A2AClient:
    """Call one remote A2A agent. Supply ``transport`` to reuse a host's egress."""

    def __init__(
        self,
        *,
        timeout: float = 300.0,
        poll_interval: float = 2.0,
        request_timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if timeout <= 0 or poll_interval <= 0 or request_timeout <= 0:
            raise ValueError("A2A client timeouts must be positive")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.request_timeout = min(request_timeout, timeout)
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.request_timeout,
            transport=self._transport,
            follow_redirects=False,
        )

    @staticmethod
    async def _json(response: httpx.Response) -> Any:
        response.raise_for_status()
        encoding = response.headers.get("content-encoding", "identity").strip().lower()
        if encoding != "identity":
            raise ValueError("A2A response encoding is unsupported")
        if response.is_stream_consumed:
            if len(response.content) > _MAX_RESPONSE_BYTES:
                raise ValueError("A2A response exceeds its bound")
            return json.loads(response.content)
        body = bytearray()
        async for chunk in response.aiter_raw():
            if len(chunk) > _MAX_RESPONSE_BYTES - len(body):
                raise ValueError("A2A response exceeds its bound")
            body.extend(chunk)
        return json.loads(body)

    async def fetch_card(self, base_url: str) -> AgentCard | None:
        """Fetch and validate a peer's agent card; ``None`` when unusable."""
        try:
            async with (
                asyncio.timeout(self.timeout),
                self._client() as client,
                client.stream(
                    "GET",
                    base_url.rstrip("/") + CARD_PATH,
                    headers={"Accept-Encoding": "identity"},
                ) as response,
            ):
                data = await self._json(response)
            return AgentCard.model_validate(data)
        except (
            httpx.HTTPError,
            httpx.StreamError,
            ValueError,
            ValidationError,
            TimeoutError,
        ):
            return None

    async def _rpc(
        self,
        client: httpx.AsyncClient,
        url: str,
        method: str,
        params: dict[str, Any],
        rid: int,
    ) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": rid}
        async with client.stream(
            "POST", url, json=payload, headers={"Accept-Encoding": "identity"}
        ) as response:
            data = await self._json(response)
        return _validate_rpc_response(data, rid)

    async def _exchange(
        self, client: httpx.AsyncClient, url: str, message: A2AMessage
    ) -> A2ATask:
        sent = await self._rpc(
            client, url, "message/send", {"message": message.wire()}, 1
        )
        if "error" in sent:
            raise _PeerRejected("A2A peer rejected the request")
        task = A2ATask.model_validate(sent.get("result"))
        task_id = task.id
        while task.pending:
            await asyncio.sleep(self.poll_interval)
            polled = await self._rpc(client, url, "tasks/get", {"id": task_id}, 2)
            if "error" in polled:
                raise _PeerRejected("A2A peer rejected task polling")
            task = _matching_task(polled.get("result"), task_id)
        return task

    async def send(self, url: str, text: str) -> A2AResult:
        """Send one user text message and wait for the task's agent reply."""
        message = A2AMessage.user_text(text)
        try:
            async with asyncio.timeout(self.timeout), self._client() as client:
                task = await self._exchange(client, url, message)
        except TimeoutError:
            return A2AResult(error="A2A execution deadline exceeded")
        except _PeerRejected as exc:
            return A2AResult(error=str(exc))
        except (httpx.HTTPError, httpx.StreamError, ValueError, ValidationError) as exc:
            return A2AResult(error=f"A2A communication failed ({type(exc).__name__})")
        reply = task.last_agent_message()
        if task.status.state != "completed" or reply is None:
            return A2AResult(error=f"A2A task ended {task.status.state}")
        return A2AResult(content=reply.text(), metadata=dict(reply.metadata))
