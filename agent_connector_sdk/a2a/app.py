"""Server-side A2A application factory (needs the ``a2a`` extra).

CONCEPT:SDK-CONNECTOR-CONTROL-R014.21

Builds a fasta2a ASGI app for a pydantic-ai agent. The caller supplies the
broker and storage; this SDK holds no task store. A host mounts the returned
app behind its own admission and authentication.
"""

from __future__ import annotations

import importlib
from collections.abc import AsyncIterator
from typing import Any

from .models import AgentSkill

__all__ = ["create_a2a_app", "require_a2a_extra"]


def require_a2a_extra(feature: str) -> None:
    """Raise ``ImportError`` naming the ``a2a`` extra when it is absent."""
    missing = []
    for name in ("fasta2a", "starlette"):
        try:
            importlib.import_module(name)
        except ImportError:
            missing.append(name)
    if missing:
        raise ImportError(
            f"{feature} needs {' and '.join(missing)}, which the base install of "
            'agent-connector-sdk leaves out; install "agent-connector-sdk[a2a]"'
        )


def create_a2a_app(
    agent: Any,
    *,
    name: str,
    url: str,
    version: str,
    description: str = "",
    skills: list[AgentSkill] | None = None,
    storage: Any,
    broker: Any,
) -> Any:
    """Return the fasta2a application for ``agent`` with the given card fields."""
    require_a2a_extra("create_a2a_app")
    from fasta2a import FastA2A, Skill
    from fasta2a.pydantic_ai import AgentWorker
    from starlette.types import ASGIApp  # noqa: F401 - the extra's contract

    worker = AgentWorker(agent=agent, broker=broker, storage=storage)
    card_skills = [
        Skill(
            id=skill.id,
            name=skill.name,
            description=skill.description,
            tags=list(skill.tags),
            input_modes=list(skill.input_modes),
            output_modes=list(skill.output_modes),
        )
        for skill in skills or []
    ]

    async def lifespan(
        app: Any,
    ) -> AsyncIterator[None]:  # pragma: no cover - exercised by the host
        async with app.task_manager, worker.run():
            yield

    from contextlib import asynccontextmanager

    return FastA2A(
        storage=storage,
        broker=broker,
        name=name,
        url=url,
        version=version,
        description=description or None,
        skills=card_skills,
        lifespan=asynccontextmanager(lifespan),
    )
