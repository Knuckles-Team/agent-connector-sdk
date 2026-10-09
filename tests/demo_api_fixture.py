"""Shared demo API-client hierarchy for tool-surface derivation tests.

Used by both the condensed tool surface (``test_tool_surface.py``) and the
opt-in per-client-method tool derivation (``test_method_tools.py``): a small
class hierarchy with a base-infrastructure method that must never become a
tool, a destructive method, and two domain classes whose class-name prefix
derivation can be exercised.
"""

from __future__ import annotations

__all__ = [
    "DemoApiBase",
    "DemoApiItems",
    "DemoApiUsers",
    "get_client",
    "get_client_async",
]


class DemoApiBase:
    def authenticate(self) -> None:
        """Infrastructure, never a tool."""


class DemoApiItems(DemoApiBase):
    def get_item(self, item_id: str) -> dict[str, str]:
        """Fetch one item."""
        return {"id": item_id}

    def delete_item(self, item_id: str) -> str:
        """Delete one item."""
        return item_id


class DemoApiUsers(DemoApiItems):
    def list_users(self) -> list[str]:
        """List users."""
        return ["u1"]


def get_client() -> DemoApiUsers:
    return DemoApiUsers()


async def get_client_async() -> DemoApiUsers:
    return DemoApiUsers()
