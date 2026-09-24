"""Run one connector decision point through EG: ``Decide`` first, the
deterministic fallback on anything else.

Ported (not imported -- the SDK must never depend on the agent control
plane) from ``agent_utilities.decide.transport``/``.runner``'s identical
contract, trimmed to this package's two evaluate-only points and with no
escalation/resolution path (neither EH-042 nor EH-043 is an escalating
point -- see ``agent_utilities/decide/points.py``'s own registry, where
only entity-resolution/schema-mapping/contradiction/tool-risk set
``escalate=True``).

The contract every call site gets, exactly as before this module existed:

1. an unbound point (no :class:`~agent_connector_sdk.decide.points.Binding`
   published) never calls EG -- the fallback answers (``unbound``);
2. otherwise EG's ``Decide`` is asked over the offered options; an executed,
   offered option is the answer, anything else leaves the fallback
   answering;
3. the record EG returned (executed or abstained) is made durable through
   the decision log per the point's
   :class:`~agent_connector_sdk.decide.points.LogMode`;
4. a transport failure -- EG down, slow, or a sync call site with no engine
   loop to block on -- costs exactly the fallback, never a raised exception,
   and the choice says so in ``reason``.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from agent_connector_sdk.decide.options import Option, declared_source
from agent_connector_sdk.decide.outcome import (
    Choice,
    Reading,
    read_batch,
    request_for,
    sampled,
)
from agent_connector_sdk.decide.points import (
    EMPTY_BINDINGS,
    POINTS,
    Bindings,
    DecisionPoint,
    LogMode,
)
from agent_connector_sdk.ports.decide_runner import Fallback

logger = logging.getLogger(__name__)

#: The longest a sync call site waits for EG before it falls back.
DEFAULT_SYNC_TIMEOUT_S = 2.0

__all__ = [
    "DEFAULT_SYNC_TIMEOUT_S",
    "DecideTransport",
    "DecideUnavailable",
    "EpistemicGraphDecisionRunner",
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
    this whole module. ``epistemic_graph.generated.query.send_decide`` is on
    published EG ``main`` today; the generic per-point recording method
    (``DecisionLog.commit``/``.resolve``,
    ``epistemic_graph.generated.coordination.send_decision_log``) ships on
    EG's ``feat/decide-consumers`` branch and has not landed yet. This
    resolves both the same way, so recording starts the moment that branch
    lands and the shared wheel is restaged, with no SDK code change.
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


@dataclass(frozen=True, slots=True)
class _Prepared:
    point: DecisionPoint
    request: dict[str, Any] | None
    offered: frozenset[str]


def _loggable(point: DecisionPoint, record: Mapping[str, Any]) -> bool:
    if point.log_mode is LogMode.NEVER:
        return False
    return point.log_mode is LogMode.ALWAYS or sampled(point, record)


def _unavailable(exc: BaseException) -> Reading:
    return Reading(None, f"unavailable: {type(exc).__name__}: {exc}", None, {})


_UNBOUND = Reading(None, "unbound", None, {})


def _settle(reading: Reading, fallback: Fallback) -> Choice:
    """The choice: EG's answer when it decided, else the deterministic fallback."""
    if reading.option_id is not None:
        return Choice(reading.option_id, True, reading.reason, {})
    return Choice(fallback(), False, reading.reason, reading.advisory)


@dataclass
class EpistemicGraphDecisionRunner:
    """Decide connector points through EG's generated ``Decide``, recording
    the outcome via the decision log when bound and loggable; otherwise
    exactly the deterministic fallback -- the same contract
    :func:`agent_connector_sdk.decide.choose` documents for no runner
    installed at all.

    Satisfies :class:`agent_connector_sdk.ports.decide_runner.DecisionRunner`.
    """

    transport: DecideTransport
    tenant: str
    bindings: Bindings = EMPTY_BINDINGS
    points: Mapping[str, DecisionPoint] = field(default_factory=lambda: dict(POINTS))

    def _prepare(
        self,
        question_id: str,
        options: Sequence[Option],
        params: Iterable[Mapping[str, Any]],
        candidates: Mapping[str, Any] | None,
    ) -> _Prepared:
        point = self.points[question_id]
        offered = frozenset(o.option_id for o in options)
        binding = self.bindings.binding_for(point)
        if binding is None or not offered:
            return _Prepared(point, None, offered)
        request = request_for(
            point,
            binding,
            tenant=self.tenant,
            candidates=candidates or declared_source(options),
            params=params,
        )
        return _Prepared(point, request, offered)

    async def _log(
        self, point: DecisionPoint, record: Mapping[str, Any] | None
    ) -> None:
        if record is None or not _loggable(point, record):
            return
        try:
            await self.transport.log({"op": "commit", "record": dict(record)})
        except Exception as exc:
            logger.warning("decision %s not logged: %s", point.question_id, exc)

    async def _consult(self, prepared: _Prepared) -> Reading:
        """Ask EG and log its record; any failure is a reading, never a raise."""
        if prepared.request is None:
            return _UNBOUND
        try:
            batch = await self.transport.decide(prepared.request)
        except Exception as exc:
            logger.warning(
                "decision %s unavailable: %s", prepared.point.question_id, exc
            )
            return _unavailable(exc)
        reading = read_batch(batch, prepared.offered)
        await self._log(prepared.point, reading.record)
        return reading

    #: ``choose`` keeps only its three most-used parameters typed by name and
    #: forwards the rest (``params``, ``candidates``) as ``**kwargs`` to
    #: :meth:`achoose` -- the single implementation -- instead of restating
    #: :class:`agent_connector_sdk.ports.decide_runner.DecisionRunner`'s
    #: canonical signature a second time in this class.
    def choose(
        self,
        question_id: str,
        options: Sequence[Option],
        fallback: Fallback,
        **kwargs: Any,
    ) -> Choice:
        """Decide from a sync call site by bridging to :meth:`achoose`.

        The bridge itself -- not this runner's own decision logic -- is what
        can fail here (no engine loop to block on, or a timeout); that still
        costs only the deterministic fallback, never a raised exception.
        """
        try:
            return cast(
                Choice,
                self.transport.run(
                    self.achoose(question_id, options, fallback, **kwargs)
                ),
            )
        except Exception as exc:
            logger.warning("decision transport unavailable: %s", exc)
            return _settle(_unavailable(exc), fallback)

    #: Kept ``**kwargs``, like :meth:`choose`, so this -- the single real
    #: implementation -- does not restate
    #: :class:`agent_connector_sdk.ports.decide_runner.DecisionRunner`'s
    #: canonical signature (``ports/decide_runner.py``, defined once) a
    #: second time; ``params``/``candidates`` are read out with the same
    #: defaults the protocol declares.
    async def achoose(
        self,
        question_id: str,
        options: Sequence[Option],
        fallback: Fallback,
        **kwargs: Any,
    ) -> Choice:
        """Decide from an async call site (the single implementation)."""
        params: Iterable[Mapping[str, Any]] = kwargs.get("params", ())
        candidates: Mapping[str, Any] | None = kwargs.get("candidates")
        prepared = self._prepare(question_id, options, params, candidates)
        reading = await self._consult(prepared)
        return _settle(reading, fallback)
