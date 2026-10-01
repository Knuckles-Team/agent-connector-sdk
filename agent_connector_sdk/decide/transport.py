"""EG's generated ``Decide``/decision-log senders behind one small transport port.

Split from :mod:`agent_connector_sdk.decide.epistemic_graph` (the runner) so the
wire half -- dynamic sender lookup, the transport protocol, and the
engine-loop bridging for sync call sites -- stays one focused module.
"""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

#: The longest a sync call site waits for EG before it falls back.
DEFAULT_SYNC_TIMEOUT_S = 2.0

__all__ = [
    "DEFAULT_SYNC_TIMEOUT_S",
    "DecideTransport",
    "DecideUnavailable",
    "GeneratedTransport",
]


class DecideUnavailable(RuntimeError):
    """The generated EG sender this transport needs is not published yet, or
    a sync call site has no engine loop it could safely block on.

    Always caught, never let through to a call site: it costs exactly the
    deterministic fallback.
    """


def _generated(module: str, name: str) -> Any:
    """One generated EG sender, resolved dynamically.

    A version of ``epistemic-graph`` that has not published ``name`` yet (or
    has retired it) costs only :class:`DecideUnavailable` -- the
    deterministic fallback -- at CALL time, never an import-time failure of
    this whole module. ``epistemic_graph.generated.query.send_decide`` is
    published today; the generic per-point recording method
    (``DecisionLog.commit``/``.resolve``,
    ``epistemic_graph.generated.coordination.send_decision_log``) is not yet
    published. This resolves both the same way, so recording starts the
    moment EG publishes it and the shared wheel is restaged, with no SDK
    code change.
    """
    try:
        loaded = importlib.import_module(f"epistemic_graph.generated.{module}")
    except ImportError as exc:
        raise DecideUnavailable(f"EG generated module {module!r} is absent") from exc
    found = getattr(loaded, name, None)
    if found is None:
        raise DecideUnavailable(f"EG does not yet generate {module}.{name}")
    return found


class DecideTransport(Protocol):
    """Send one ``Decide`` request or decision-log op; return the payload."""

    async def decide(self, request: Mapping[str, Any]) -> Any: ...

    async def log(self, op: Mapping[str, Any]) -> Any: ...

    def run(self, call: Any) -> Any:
        """Drive one of the coroutines above from a sync call site."""
        ...


def _on_loop(loop: asyncio.AbstractEventLoop) -> bool:
    """True on ``loop``'s own thread, where blocking on it would deadlock."""
    try:
        return asyncio.get_running_loop() is loop
    except RuntimeError:
        return False


def _payload(result: Any) -> Any:
    return getattr(result, "payload", result)


@dataclass(frozen=True, slots=True)
class GeneratedTransport:
    """EG's generated ``Decide``/decision-log senders, bound to one client and graph.

    Async callers await it directly; sync call sites run the same coroutine
    on the given engine loop (from a *different* thread -- calling this from
    the loop's own thread would deadlock, and :meth:`run` refuses instead),
    bounded by a timeout so a slow engine can only ever cost the fallback.

    EG's own literal ``DecisionCommit`` method
    (``epistemic_graph.generated.decision_commit``, already published) is a
    different, narrower thing -- the constraint-solver agent-ASSEMBLY
    decision commit (its ``DecisionQuestion`` enum has exactly one member,
    ``ASSEMBLE``); its request and record shapes (``AssemblyRequest``,
    ``SlotAssignment``, ``Certificate``, ...) do not fit an arbitrary typed
    question with caller-declared candidates, so it is not used here.
    """

    client: Any
    graph: str | None = None
    loop: asyncio.AbstractEventLoop | None = None
    sync_timeout_s: float = DEFAULT_SYNC_TIMEOUT_S

    async def decide(self, request: Mapping[str, Any]) -> Any:
        send = _generated("query", "send_decide")
        return _payload(await send(self.client, {"request": dict(request)}, self.graph))

    async def log(self, op: Mapping[str, Any]) -> Any:
        send = _generated("coordination", "send_decision_log")
        return _payload(await send(self.client, {"op": dict(op)}, self.graph))

    def run(self, call: Any) -> Any:
        if self.loop is None or self.loop.is_closed() or _on_loop(self.loop):
            call.close()
            raise DecideUnavailable("no engine loop a sync decision may block on")
        future = asyncio.run_coroutine_threadsafe(call, self.loop)
        return future.result(timeout=self.sync_timeout_s)
