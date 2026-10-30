"""The actor on whose behalf connector work runs.

Replaces the connector-facing part of ``agent_utilities.security.brain_context``
(``ActorContext``, ``use_actor``, ``current_actor``) and
``agent_utilities.security.actor_identity.ActorType``. The context is carried in
a :mod:`contextvars` variable so it follows async tasks.

Nothing has to bind an actor first. With none bound, :func:`current_actor`
resolves one from the transport of the current request (see
:mod:`scion_sdk.mcp.actor_binding`): :data:`SYSTEM_ACTOR` for a local
transport, process startup or background work with no request; the verified
token's actor for authenticated HTTP; and :data:`ANONYMOUS_ACTOR`, which holds
no entitlements, for unauthenticated HTTP (including a no-auth HTTP server).
:func:`use_actor` is only an explicit override, for tests and embedding.

Actor type is descriptive provenance; it never grants authorization.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "ANONYMOUS_ACTOR",
    "SYSTEM_ACTOR",
    "ActorContext",
    "ActorType",
    "AuthenticationRequiredError",
    "IdentityRequiredError",
    "current_actor",
    "is_anonymous",
    "require_authenticated_actor",
    "use_actor",
]


class ActorType(StrEnum):
    """Provenance classification for an actor."""

    HUMAN = "human"
    AI_AGENT = "ai_agent"
    AUTOMATED_SERVICE = "automated_service"
    HYBRID_TEAM = "hybrid_team"
    SYSTEM = "system"
    ANONYMOUS = "anonymous"


@dataclass(frozen=True)
class ActorContext:
    """Who is acting, in which tenant, with which effective roles.

    ``authenticated`` is true only when the identity was established from a
    verified credential or from the local process boundary
    (:data:`SYSTEM_ACTOR`); a caller-supplied identity stays unauthenticated.
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


#: The actor for a local transport (stdio or an in-process client): the caller
#: already holds the server process's own authority, so it reaches every resource.
SYSTEM_ACTOR = ActorContext(
    actor_id="system",
    actor_type=ActorType.SYSTEM,
    tenant_id="local",
    roles=("system",),
    authenticated=True,
)

#: The actor for an unauthenticated network caller. It holds no roles and no
#: groups, so every entitlement resolves empty for it.
ANONYMOUS_ACTOR = ActorContext(actor_id="anonymous", actor_type=ActorType.ANONYMOUS)


class IdentityRequiredError(PermissionError):
    """An operation's identity requirement is not met by the resolved actor."""

    reason = "identity_required"


class AuthenticationRequiredError(IdentityRequiredError):
    """An operation needs an authenticated actor and the bound one is not."""

    reason = "authentication_required"


_current: contextvars.ContextVar[ActorContext | None] = contextvars.ContextVar(
    "scion_sdk_actor", default=None
)


def current_actor() -> ActorContext:
    """Return the bound actor, else the actor the current transport implies.

    Never raises because nothing called :func:`use_actor`: an explicit binding
    wins; otherwise the actor is resolved per request from the transport.
    """
    actor = _current.get()
    if actor is not None:
        return actor
    return _transport_actor()


def _transport_actor() -> ActorContext:
    try:
        from scion_sdk.mcp.actor_binding import request_actor
    except ImportError:  # no [mcp] extra: no served transport can exist
        return SYSTEM_ACTOR
    return request_actor()


def is_anonymous(actor: ActorContext) -> bool:
    """True for the unauthenticated network caller (:data:`ANONYMOUS_ACTOR`)."""
    return actor.actor_type is ActorType.ANONYMOUS and not actor.authenticated


def require_authenticated_actor() -> ActorContext:
    """Return the bound actor when it is authenticated.

    Use this for writes and entitlement-gated mutations.

    Raises:
        AuthenticationRequiredError: when the resolved actor is not authenticated.
    """
    actor = current_actor()
    if not actor.authenticated:
        raise AuthenticationRequiredError("this operation requires authentication")
    return actor


@contextmanager
def use_actor(actor: ActorContext) -> Iterator[ActorContext]:
    """Bind ``actor`` for the enclosed block and restore the previous one after."""
    token = _current.set(actor)
    try:
        yield actor
    finally:
        _current.reset(token)
