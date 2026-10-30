"""Progress notifications from a connector tool to its MCP client.

Replaces ``agent_utilities.mcp.context_helpers.ctx_progress``.
"""

from __future__ import annotations

import logging
import math
from typing import Any

__all__ = ["ctx_progress"]

_logger = logging.getLogger(__name__)


async def ctx_progress(
    ctx: Any, progress: float, total: float | None = 100, *, message: str | None = None
) -> None:
    """Report ``progress`` of ``total`` when a FastMCP ``Context`` is present.

    Delivery is best-effort: a client that cannot receive the notification does
    not fail the tool; the failure is logged.

    Raises:
        ValueError: ``progress`` is negative or not finite, or exceeds a finite
            positive ``total``.
    """
    finite = math.isfinite(progress) and (total is None or math.isfinite(total))
    outside = total is not None and (total <= 0 or progress > total)
    if not finite or progress < 0 or outside:
        raise ValueError("progress must be finite, non-negative and within total")
    if not ctx:
        return
    try:
        await ctx.report_progress(progress=progress, total=total, message=message)
    except Exception as exc:  # notification delivery is best-effort by contract
        _logger.warning("MCP progress notification failed: %s", exc)
