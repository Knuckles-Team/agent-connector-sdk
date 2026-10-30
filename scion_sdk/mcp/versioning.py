"""Tool version metadata for MCP tools (SCION-CONNECTOR-CONTROL-R014.3).

Moved from agent-utilities so connectors stamp tool versions without the harness.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

__all__ = ["tool_version"]

_F = TypeVar("_F", bound=Callable[..., Awaitable[Any]])


def tool_version(version: str) -> Callable[[_F], _F]:
    """Attach ``__agentic_version__`` and a ``Version:`` docstring line to an async tool."""

    def decorator(func: _F) -> _F:
        func.__agentic_version__ = version  # type: ignore[attr-defined]
        if func.__doc__:
            func.__doc__ = f"{func.__doc__.rstrip()}\n\n    Version: {version}\n"
        else:
            func.__doc__ = f"Version: {version}\n"

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
