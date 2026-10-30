"""Value types and constants for governed A2A agent-card discovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

AGENT_CARD_PATH = "/.well-known/agent-card.json"
DEFAULT_DISCOVERY_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_AGENT_CARD_BYTES = 256 * 1024
DEFAULT_AGENT_CARD_CACHE_ENTRIES = 64

_RefusalReason = Literal["not_found", "not_json", "oversize", "egress_blocked"]


@dataclass(frozen=True, slots=True)
class DiscoveredAgentCard:
    """One bounded, source-pinned observation of a remote agent card."""

    base_url: str
    card: dict[str, Any]
    fetched_at: str
    etag: str | None
    skills: tuple[str, ...]

    @property
    def source_url(self) -> str:
        """The exact well-known resource that produced ``card``."""
        return f"{self.base_url.rstrip('/')}{AGENT_CARD_PATH}"


@dataclass(frozen=True, slots=True)
class AgentCardRefused:
    """A card that was not admitted to the extractor change set."""

    reason: _RefusalReason


def _refused(reason: _RefusalReason) -> AgentCardRefused:
    return AgentCardRefused(reason=reason)
