"""The pluggable EG ``Decide`` port for the SDK's own decision consumers.

Mirrors ``agent_utilities.decide.runner.DecisionRunner``'s shape (DESIGN §1 of
lane decide-consumers) without importing ``agent_utilities`` -- the SDK must
never depend on the agent control plane (see ``pyproject.toml``'s dependency
comment) or on EG beyond its existing generated types.
:class:`~agent_connector_sdk.decide.epistemic_graph.EpistemicGraphDecisionRunner`
is the SDK's own real implementation, calling EG's generated ``Decide``
sender (and, once EG's ``feat/decide-consumers`` branch lands, its decision
log) over a verified client -- installed at the ``connector-sync``
composition root (:func:`agent_connector_sdk.runner.composition.default_services`)
when this process has one. With no runner installed, every call site in
:mod:`agent_connector_sdk.decide.consumers` is exactly its old deterministic
rule.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agent_connector_sdk.decide.options import Option
    from agent_connector_sdk.decide.outcome import Choice

#: Produces the deterministic answer when EG does not decide (no runner
#: installed, EG abstains, gives only an advisory, or names an option the
#: caller did not offer).
Fallback = Callable[[], str]


@runtime_checkable
class DecisionRunner(Protocol):
    """Decide one question from a declared set of options.

    An executed, offered option is the answer (``Choice.decided`` is
    ``True``); anything else -- an unbound question, a transport failure, an
    abstention, an advisory-only outcome, or an option the caller never
    offered -- means the implementation calls ``fallback()`` itself and
    returns that answer with ``decided=False`` and a ``reason`` naming why.
    A call site never needs to re-derive the fallback: ``Choice.option_id``
    is always a concrete answer once a runner replies.
    """

    def choose(
        self,
        question_id: str,
        options: Sequence[Option],
        fallback: Fallback,
        **kwargs: Any,
    ) -> Choice:
        """Decide from a sync call site.

        ``**kwargs`` is exactly :meth:`achoose`'s ``params``/``candidates`` --
        kept generic here so the one fully typed signature (an implementer's
        real sync/async pair almost always shares one body, the sync half
        bridging to the async one) is written only once, on :meth:`achoose`.
        """
        ...

    async def achoose(
        self,
        question_id: str,
        options: Sequence[Option],
        fallback: Fallback,
        *,
        params: Iterable[Mapping[str, Any]] = (),
        candidates: Mapping[str, Any] | None = None,
    ) -> Choice:
        """Decide from an async call site -- the canonical signature.

        An unbound question, a transport failure, an abstention, an
        advisory-only outcome, or an option the caller never offered all mean
        the implementation calls ``fallback()`` itself and returns that
        answer with ``decided=False`` and a ``reason`` naming why.
        """
        ...


__all__ = ["DecisionRunner", "Fallback"]
