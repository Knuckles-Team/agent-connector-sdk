"""Bounded JSON-RPC client for one A2A exchange.

CONCEPT:SDK-CONNECTOR-CONTROL-R014.21

``message/send`` then ``tasks/get`` polling until the task leaves a pending
state or the deadline passes. Failures come back as an :class:`A2AResult` with
a fixed message; remote error bodies are never echoed.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import ValidationError

from .models import A2AMessage, A2ATask, AgentCard

CARD_PATH = "/.well-known/agent-card.json"
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


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
    def _json(response: httpx.Response) -> Any:
        response.raise_for_status()
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise ValueError("A2A response exceeds its bound")
        return response.json()

    async def fetch_card(self, base_url: str) -> AgentCard | None:
        """Fetch and validate a peer's agent card; ``None`` when unusable."""
        try:
            async with self._client() as client:
                data = self._json(await client.get(base_url.rstrip("/") + CARD_PATH))
            return AgentCard.model_validate(data)
        except (httpx.HTTPError, ValueError, ValidationError):
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
        data = self._json(await client.post(url, json=payload))
        if not isinstance(data, dict):
            raise ValueError("A2A response root must be an object")
        return data

    async def send(self, url: str, text: str) -> A2AResult:
        """Send one user text message and wait for the task's agent reply."""
        message = A2AMessage.user_text(text)
        try:
            async with asyncio.timeout(self.timeout), self._client() as client:
                sent = await self._rpc(
                    client, url, "message/send", {"message": message.wire()}, 1
                )
                if "error" in sent:
                    return A2AResult(error="A2A peer rejected the request")
                task = A2ATask.model_validate(sent.get("result"))
                while task.pending:
                    await asyncio.sleep(self.poll_interval)
                    polled = await self._rpc(
                        client, url, "tasks/get", {"id": task.id}, 2
                    )
                    if "error" in polled:
                        return A2AResult(error="A2A peer rejected task polling")
                    task = A2ATask.model_validate(polled.get("result"))
        except TimeoutError:
            return A2AResult(error="A2A execution deadline exceeded")
        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            return A2AResult(error=f"A2A communication failed ({type(exc).__name__})")
        reply = task.last_agent_message()
        if task.status.state != "completed" or reply is None:
            return A2AResult(error=f"A2A task ended {task.status.state}")
        return A2AResult(content=reply.text(), metadata=dict(reply.metadata))
