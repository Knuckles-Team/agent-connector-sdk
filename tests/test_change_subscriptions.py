"""Change events: notifications, listen streams, and servers that serve them."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import anyio
import mcp_types
import pytest
from fastmcp import Client, Context, FastMCP
from mcp.server.subscriptions import (
    PromptsListChanged,
    ResourcesListChanged,
    ResourceUpdated,
    ServerEvent,
    ToolsListChanged,
)

from agent_connector_sdk.mcp.change_events import (
    announce_content_changed,
    announce_resource_updated,
    change_bus,
    serve_change_subscriptions,
)
from agent_connector_sdk.mcp.server import create_mcp_server
from agent_connector_sdk.ports.change_source import ChangeEvent, ChangeSource
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.transports.mcp import McpTransport
from agent_connector_sdk.transports.mcp_changes import (
    ChangeFeed,
    forward_listen_events,
    notification_event,
    server_event,
)
from agent_connector_sdk.transports.mcp_session import McpClientSession

LISTS = {ChangeEvent("tools"), ChangeEvent("prompts"), ChangeEvent("resources")}


def _server() -> FastMCP[Any]:
    mcp: FastMCP[Any] = FastMCP("changes", version="1.0.0")

    @mcp.tool()
    async def announce(ctx: Context) -> str:
        """Send a prompt list-changed notification inside the request."""
        await ctx.send_notification(mcp_types.PromptListChangedNotification())
        return "sent"

    return mcp


def test_notifications_and_listen_events_map_to_changes() -> None:
    updated = mcp_types.ResourceUpdatedNotification(
        params=mcp_types.ResourceUpdatedNotificationParams(uri="data://x")
    )
    assert {
        notification_event(mcp_types.ToolListChangedNotification()),
        notification_event(mcp_types.PromptListChangedNotification()),
        notification_event(mcp_types.ResourceListChangedNotification()),
    } == LISTS
    assert notification_event(updated) == ChangeEvent("resource", "data://x")
    assert notification_event(ValueError("a transport error")) is None
    events = (ToolsListChanged(), PromptsListChanged(), ResourcesListChanged())
    assert {server_event(event) for event in events} == LISTS
    assert server_event(ResourceUpdated(uri="data://y")) == ChangeEvent(
        "resource", "data://y"
    )


async def test_change_feed_collapses_pending_duplicates() -> None:
    feed = ChangeFeed()
    await feed.on_message(mcp_types.ToolListChangedNotification())
    await feed.on_message(mcp_types.ToolListChangedNotification())
    feed.add(ChangeEvent("resource", "data://x"))
    assert await feed.next_changes() == {
        ChangeEvent("tools"),
        ChangeEvent("resource", "data://x"),
    }
    with anyio.move_on_after(0.05) as waiting:
        await feed.next_changes()
    assert waiting.cancelled_caught


async def test_listen_streams_deliver_published_changes() -> None:
    mcp = _server()
    serve_change_subscriptions(mcp)
    async with McpTransport().session(TransportEndpoint(in_process=mcp)) as session:
        assert isinstance(session, ChangeSource)
        assert await session.watch(["data://x"])
        assert await session.watch(["data://x", "data://y"])
        await announce_resource_updated(mcp, "data://y")
        await announce_content_changed(mcp)
        seen: set[ChangeEvent] = set()
        with anyio.fail_after(5):
            while len(seen) < 4:
                seen |= await session.next_changes()
    assert seen == LISTS | {ChangeEvent("resource", "data://y")}


class _SwitchBus:
    """Publishes an update to the current listeners when a new stream subscribes."""

    def __init__(self) -> None:
        self.listeners: dict[object, Callable[[ServerEvent], None]] = {}
        self.publish_on_subscribe = False

    async def publish(self, event: ServerEvent) -> None:
        for listener in list(self.listeners.values()):
            listener(event)

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        if self.publish_on_subscribe:
            self.publish_on_subscribe = False
            for current in list(self.listeners.values()):
                current(ResourceUpdated(uri="data://during-switch"))
        token = object()
        self.listeners[token] = listener
        return lambda: self.listeners.pop(token, None)


async def test_resubscribing_loses_no_event_published_during_the_switch() -> None:
    mcp = _server()
    bus = _SwitchBus()
    serve_change_subscriptions(mcp, bus)
    async with McpTransport().session(TransportEndpoint(in_process=mcp)) as session:
        assert isinstance(session, ChangeSource)
        assert await session.watch(["data://during-switch"])
        bus.publish_on_subscribe = True
        assert await session.watch(["data://during-switch", "data://new"])
        with anyio.fail_after(5):
            assert await session.next_changes() == {
                ChangeEvent("resource", "data://during-switch")
            }


async def test_servers_without_listen_still_report_their_notifications() -> None:
    mcp = _server()
    async with McpTransport().session(TransportEndpoint(in_process=mcp)) as session:
        assert isinstance(session, McpClientSession)
        assert not await session.watch([])
        await session.call_tool("announce", {})
        with anyio.fail_after(5):
            assert await session.next_changes() == {ChangeEvent("prompts")}
    with pytest.raises(LookupError):
        change_bus(mcp)
    async with Client(mcp) as client:
        session = McpClientSession(client, feed=ChangeFeed())
        assert not await session.watch(["data://x"])


async def test_forward_listen_events_reports_its_stream() -> None:
    mcp = _server()
    bus = serve_change_subscriptions(mcp)
    assert change_bus(mcp) is bus
    feed = ChangeFeed()
    async with Client(mcp) as client, anyio.create_task_group() as tasks:
        scope = await tasks.start(
            forward_listen_events, client.session, feed, ("data://z",)
        )
        assert scope is not None
        await announce_resource_updated(mcp, "data://z")
        with anyio.fail_after(5):
            assert await feed.next_changes() == {ChangeEvent("resource", "data://z")}
        scope.cancel()


async def test_create_mcp_server_serves_change_subscriptions() -> None:
    _, mcp, _ = create_mcp_server("changes-mcp", version="1.0.0", command_args=[])
    assert change_bus(mcp) is not None
    async with Client(mcp) as client:
        capabilities = client.server_capabilities
        assert capabilities.tools is not None and capabilities.tools.list_changed
        assert capabilities.resources is not None and capabilities.resources.subscribe


def test_endpoint_bearer_token_is_hidden_and_url_only() -> None:
    endpoint = TransportEndpoint(
        url="https://mcp.example.invalid/mcp", bearer_token="example-resolved-token"
    )
    assert "example-resolved-token" not in repr(endpoint)
    with pytest.raises(ValueError, match="bearer_token"):
        TransportEndpoint(command="demo-mcp", bearer_token="example-resolved-token")
