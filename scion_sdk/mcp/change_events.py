"""Serve ``subscriptions/listen`` from a connector server and publish changes.

A connector that serves listen streams lets the connector-sync runner react to
changes instead of polling: when a tool, prompt or resource list changes, the
runner re-provisions the content pack; when a data resource is updated, it
syncs the presets mapped to that resource (RF-ADR-009 sections 2.1 and 2.2).
FastMCP does not serve ``subscriptions/listen`` by itself, so
:func:`serve_change_subscriptions` installs the MCP SDK's listen handler on the
server and keeps the bus events are published on.
"""

from __future__ import annotations

from typing import Any
from weakref import WeakKeyDictionary

import mcp_types
from fastmcp import FastMCP
from mcp.server.subscriptions import (
    InMemorySubscriptionBus,
    ListenHandler,
    PromptsListChanged,
    ResourcesListChanged,
    ResourceUpdated,
    SubscriptionBus,
    ToolsListChanged,
)

__all__ = [
    "announce_content_changed",
    "announce_resource_updated",
    "change_bus",
    "serve_change_subscriptions",
]

_BUSES: WeakKeyDictionary[FastMCP[Any], SubscriptionBus] = WeakKeyDictionary()


def serve_change_subscriptions(
    mcp: FastMCP[Any], bus: SubscriptionBus | None = None
) -> SubscriptionBus:
    """Serve ``subscriptions/listen`` on ``mcp`` and return its event bus.

    ``bus`` defaults to an in-process bus; pass a shared implementation to fan
    events out across replicas.
    """
    chosen = bus if bus is not None else InMemorySubscriptionBus()
    mcp._mcp_server.add_request_handler(
        "subscriptions/listen",
        mcp_types.SubscriptionsListenRequestParams,
        ListenHandler(chosen),
    )
    _BUSES[mcp] = chosen
    return chosen


def change_bus(mcp: FastMCP[Any]) -> SubscriptionBus:
    """The bus :func:`serve_change_subscriptions` installed on ``mcp``.

    Raises:
        LookupError: the server does not serve change subscriptions.
    """
    bus = _BUSES.get(mcp)
    if bus is None:
        raise LookupError("this server does not serve change subscriptions")
    return bus


async def announce_content_changed(mcp: FastMCP[Any]) -> None:
    """Publish that the tool, prompt and resource lists may have changed."""
    bus = change_bus(mcp)
    for event in (ToolsListChanged(), PromptsListChanged(), ResourcesListChanged()):
        await bus.publish(event)


async def announce_resource_updated(mcp: FastMCP[Any], uri: str) -> None:
    """Publish that the resource at ``uri`` was updated."""
    await change_bus(mcp).publish(ResourceUpdated(uri=uri))
