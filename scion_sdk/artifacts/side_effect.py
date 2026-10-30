"""Closed vocabulary of declared tool effects."""

from enum import StrEnum

__all__ = ["SideEffect"]


class SideEffect(StrEnum):
    """Closed set of tool effects used by contract facts."""

    NONE = "none"
    WORKSPACE_WRITE = "workspace_write"
    EXTERNAL_WRITE = "external_write"
    NETWORK = "network"
