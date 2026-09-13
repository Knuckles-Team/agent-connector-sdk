"""The ``ChangeSource`` port: change events a session receives from its server.

MCP servers announce that their tools, prompts or resources changed, and that
one resource was updated. At protocol 2026-07-28 those events arrive on a
``subscriptions/listen`` stream; earlier servers send them as notifications
alongside requests. A session that implements this port presents both as
:class:`ChangeEvent` values. Events are level triggers ("this changed, refetch
if you care"), so pending duplicates collapse into one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

__all__ = ["ChangeEvent", "ChangeSource"]


@dataclass(frozen=True)
class ChangeEvent:
    """One change: a list (``tools``, ``prompts``, ``resources``) or a ``resource``."""

    kind: Literal["tools", "prompts", "resources", "resource"]
    uri: str = ""


@runtime_checkable
class ChangeSource(Protocol):
    """A session that reports server change events."""

    async def watch(self, resource_uris: Sequence[str]) -> bool:
        """Subscribe to list changes and to updates of ``resource_uris``.

        Replaces an earlier subscription. Returns ``True`` when the server
        acknowledged ``subscriptions/listen``; ``False`` means only the
        notifications the server sends on its own will arrive.
        """
        ...

    async def next_changes(self) -> frozenset[ChangeEvent]:
        """Wait for at least one change and return every change pending."""
        ...
