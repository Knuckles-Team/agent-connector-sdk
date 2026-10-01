"""Run one connector decision point through EG: ``Decide`` first, the
deterministic fallback on anything else.

Ported (not imported -- the SDK must never depend on the agent control
plane) from agent-utilities' equivalent transport/runner contract, trimmed
to this package's two evaluate-only points and with no escalation/
resolution path: neither of this package's decision points escalates.

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

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

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
from agent_connector_sdk.decide.transport import DecideTransport
from agent_connector_sdk.ports.decide_runner import Fallback

logger = logging.getLogger(__name__)

__all__ = ["EpistemicGraphDecisionRunner"]


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
