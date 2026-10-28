"""Typed declarations of connector transport behavior.

A declaration does not establish that an implementation is available. The
consumer must independently check its transport registry before use.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_connector_sdk._contract_fields import (
    ACCESS_KINDS,
    AUTH_MODELS,
    PAGINATION_MODES,
    PUSHDOWN_OPS,
    STREAM_MODES,
)

_STREAM_PROTOCOLS = frozenset({"stream_topic", "change_feed", "event_stream"})


@dataclass(frozen=True)
class TransportContract:
    """Immutable protocol and capability declaration, not an admission grant."""

    protocol: str
    auth_model: str
    paging: str = "none"
    streaming: str = "none"
    pushdown: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        """Reject unknown values and snapshot the caller's pushdown set."""
        for value, allowed, name in (
            (self.protocol, ACCESS_KINDS, "protocol"),
            (self.auth_model, AUTH_MODELS, "auth_model"),
            (self.paging, PAGINATION_MODES, "paging"),
            (self.streaming, STREAM_MODES, "streaming"),
        ):
            if not isinstance(value, str) or value not in allowed:
                raise ValueError(f"unknown transport {name}")
        raw: object = self.pushdown
        if isinstance(raw, str):
            raise ValueError("unknown transport pushdown")
        try:
            ops = frozenset(self.pushdown)
        except TypeError:
            raise ValueError("unknown transport pushdown") from None
        if not ops <= PUSHDOWN_OPS:
            raise ValueError("unknown transport pushdown")
        if self.protocol in _STREAM_PROTOCOLS and not ops <= {"time_range"}:
            raise ValueError("unsupported stream pushdown")
        object.__setattr__(self, "pushdown", ops)
