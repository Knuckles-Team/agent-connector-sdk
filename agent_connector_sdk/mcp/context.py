"""Helpers for the optional FastMCP ``Context`` handed to tool handlers.

Extracted from ``agent_utilities.mcp.context_helpers``. A missing context or a
failed elicitation always denies a destructive operation: unattended execution
is not write authorization.
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = ["ctx_confirm_destructive", "ctx_log"]

_logger = logging.getLogger(__name__)

_LOG_LEVELS = frozenset({"debug", "info", "warning", "error"})


async def ctx_confirm_destructive(ctx: Any, action_description: str) -> bool:
    """Ask the connected user to confirm a destructive operation.

    Returns:
        ``True`` only when a live context exists and the user accepted.
    """
    if not ctx:
        return False
    try:
        result = await ctx.elicit(
            f"Are you sure you want to {action_description}?", response_type=bool
        )
    except Exception as exc:  # a failed elicitation denies the operation
        _logger.warning(
            "Elicitation failed; destructive operation denied: %s",
            exc,
        )
        return False
    return bool(result.action == "accept" and bool(result.data))


async def ctx_log(
    ctx: Any, message: str, *, logger: logging.Logger, level: str = "info"
) -> None:
    """Log ``message`` to ``logger`` and, when a context is present, the client.

    Raises:
        ValueError: ``level`` is not debug, info, warning or error.
    """
    if level not in _LOG_LEVELS:
        raise ValueError(f"unsupported log level {level!r}")
    getattr(logger, level)(message)
    if not ctx:
        return
    try:
        await getattr(ctx, level)(message)
    except Exception as exc:  # client log delivery is best-effort by contract
        logger.warning("MCP client log delivery failed: %s", exc)
