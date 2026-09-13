"""The actor on whose behalf connector work runs.

Replaces the connector-facing part of ``agent_utilities.security.brain_context``
(``ActorContext``, ``use_actor``, ``current_actor``) and
``agent_utilities.security.actor_identity.ActorType``. The context is carried in
a :mod:`contextvars` variable so it follows async tasks. There is no implicit
default actor: work that needs an identity and has none bound fails closed.

Actor type is descriptive provenance; it never grants authorization.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "ActorContext",
    "ActorType",
    "IdentityRequiredError",
    "current_actor",
    "use_actor",
]


class ActorType(StrEnum):
    """Provenance classification for an actor."""

    HUMAN = "human"
    AI_AGENT = "ai_agent"
    AUTOMATED_SERVICE = "automated_service"
    HYBRID_TEAM = "hybrid_team"
    SYSTEM = "system"


@dataclass(frozen=True)
class ActorContext:
    """Who is acting, in which tenant, with which effective roles.

    ``authenticated`` is true only when the identity was established from a
    verified credential; a caller-supplied identity stays unauthenticated.
    """

    actor_id: str
    actor_type: ActorType
    tenant_id: str = ""
    roles: tuple[str, ...] = field(default_factory=tuple)
    groups: tuple[str, ...] = field(default_factory=tuple)
    authenticated: bool = False

    def __post_init__(self) -> None:
        if not self.actor_id:
            raise ValueError("actor_id must not be empty")


class IdentityRequiredError(PermissionError):
    """An operation needs a bound actor and none is bound."""


_current: contextvars.ContextVar[ActorContext | None] = contextvars.ContextVar(
    "agent_connector_sdk_actor", default=None
)


def current_actor() -> ActorContext:
    """Return the bound actor.

    Raises:
        IdentityRequiredError: when no actor is bound.
    """
    actor = _current.get()
    if actor is None:
        raise IdentityRequiredError("an actor context is required")
    return actor


@contextmanager
def use_actor(actor: ActorContext) -> Iterator[ActorContext]:
    """Bind ``actor`` for the enclosed block and restore the previous one after."""
    token = _current.set(actor)
    try:
        yield actor
    finally:
        _current.reset(token)
