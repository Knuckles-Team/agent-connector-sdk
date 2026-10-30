"""Agent-to-Agent (A2A) protocol pieces any connector or host can reuse.

CONCEPT:SCION-CONNECTOR-CONTROL-R014.21

The base install carries the wire models and the JSON-RPC client (pydantic and
httpx only). The server-side application factory needs the optional ``a2a``
extra (fasta2a and starlette); a host such as arbora mounts it behind its own
admission and authentication. Nothing here stores tasks or builds cards from a
graph: durable task state and graph-derived cards belong to the host.
"""

from __future__ import annotations

from typing import Any

from .client import A2AClient, A2AResult
from .models import (
    A2AMessage,
    A2ATask,
    A2ATaskStatus,
    AgentCard,
    AgentSkill,
    TaskState,
    TextPart,
)

__all__ = [
    "A2AClient",
    "A2AMessage",
    "A2AResult",
    "A2ATask",
    "A2ATaskStatus",
    "AgentCard",
    "AgentSkill",
    "TaskState",
    "TextPart",
    "create_a2a_app",
]


def __getattr__(name: str) -> Any:
    if name == "create_a2a_app":
        from .app import create_a2a_app

        return create_a2a_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
