"""Change events for an MCP client session: notifications and listen streams."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from contextlib import AsyncExitStack

import anyio
import mcp_types
from anyio.abc import TaskStatus
from mcp.client.session import ClientSession
from mcp.client.subscriptions import (
    ListenNotSupportedError,
    Subscription,
    listen,
)
from mcp.shared.exceptions import MCPError
from mcp.shared.subscriptions import (
    PromptsListChanged,
    ResourcesListChanged,
    ResourceUpdated,
    ServerEvent,
    ToolsListChanged,
)

from agent_connector_sdk.ports.change_source import ChangeEvent

__all__ = ["ChangeFeed", "forward_listen_events", "notification_event", "server_event"]

_logger = logging.getLogger(__name__)

_LIST_NOTIFICATIONS: tuple[tuple[type[object], ChangeEvent], ...] = (
    (mcp_types.ToolListChangedNotification, ChangeEvent("tools")),
    (mcp_types.PromptListChangedNotification, ChangeEvent("prompts")),
    (mcp_types.ResourceListChangedNotification, ChangeEvent("resources")),
)
_LIST_EVENTS: tuple[tuple[type[object], ChangeEvent], ...] = (
    (ToolsListChanged, ChangeEvent("tools")),
    (PromptsListChanged, ChangeEvent("prompts")),
    (ResourcesListChanged, ChangeEvent("resources")),
)


def notification_event(message: object) -> ChangeEvent | None:
    """The change a server notification announces, or ``None``."""
    if isinstance(message, mcp_types.ResourceUpdatedNotification):
        return ChangeEvent("resource", str(message.params.uri))
    return next(
        (event for kind, event in _LIST_NOTIFICATIONS if isinstance(message, kind)),
        None,
    )


def server_event(event: ServerEvent) -> ChangeEvent:
    """The change a ``subscriptions/listen`` event announces."""
    if isinstance(event, ResourceUpdated):
        return ChangeEvent("resource", event.uri)
    return next(change for kind, change in _LIST_EVENTS if isinstance(event, kind))


class ChangeFeed:
    """Level-triggered pending changes, fed by notifications and listen streams."""

    def __init__(self) -> None:
        self._pending: set[ChangeEvent] = set()
        self._signal = anyio.Event()

    def add(self, event: ChangeEvent) -> None:
        """Record a pending change and wake a waiting reader."""
        self._pending.add(event)
        self._signal.set()

    async def on_message(self, message: object) -> None:
        """A FastMCP client ``message_handler``: keep change notifications."""
        event = notification_event(message)
        if event is not None:
            self.add(event)

    async def next_changes(self) -> frozenset[ChangeEvent]:
        """Wait for at least one change and return every change pending."""
        await self._signal.wait()
        changes = frozenset(self._pending)
        self._pending.clear()
        self._signal = anyio.Event()
        return changes


async def _pump(subscription: Subscription, feed: ChangeFeed) -> None:
    async for event in subscription:
        feed.add(server_event(event))


async def forward_listen_events(
    session: ClientSession,
    feed: ChangeFeed,
    resource_uris: Sequence[str],
    *,
    task_status: TaskStatus[anyio.CancelScope | None] = anyio.TASK_STATUS_IGNORED,
) -> None:
    """Open one listen stream and forward its events into ``feed``.

    Reports a cancel scope for the stream through ``task_status``, or ``None``
    when the server does not serve ``subscriptions/listen``. A stream that
    fails after it was acknowledged raises, so the session is reopened.
    """
    scope = anyio.CancelScope()
    with scope:
        async with AsyncExitStack() as stack:
            subscription = await _enter_listen(stack, session, resource_uris)
            task_status.started(None if subscription is None else scope)
            if subscription is not None:
                await _pump(subscription, feed)


async def _enter_listen(
    stack: AsyncExitStack, session: ClientSession, resource_uris: Sequence[str]
) -> Subscription | None:
    stream = listen(
        session,
        tools_list_changed=True,
        prompts_list_changed=True,
        resources_list_changed=True,
        resource_subscriptions=list(resource_uris),
    )
    try:
        return await stack.enter_async_context(stream)
    except (ListenNotSupportedError, MCPError) as exc:
        _logger.info("server does not serve subscriptions/listen: %s", exc)
        return None
