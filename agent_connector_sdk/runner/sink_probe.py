"""Call a ``Sink``'s readiness bounded by a timeout, so a hung sink cannot
hang whatever awaits it (a ``/health/ready`` request, most directly).
"""

from __future__ import annotations

import anyio

from agent_connector_sdk.ports.sink import Sink, SinkReadiness

__all__ = ["probe_sink_readiness", "sink_reason"]


async def probe_sink_readiness(sink: Sink, *, timeout_seconds: float) -> SinkReadiness:
    """``await sink.readiness()``, bounded by ``timeout_seconds``."""
    with anyio.move_on_after(timeout_seconds):
        return await sink.readiness()
    return SinkReadiness(
        ready=False, reason=f"sink readiness timed out after {timeout_seconds}s"
    )


def sink_reason(state: SinkReadiness) -> str:
    """A not-ready ``state``'s reason, defaulting when a sink left it unset."""
    return state.reason if state.reason is not None else "sink not ready"
