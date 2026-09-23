"""The pluggable EG ``Decide`` port for the SDK's own decision consumers.

Mirrors ``agent_utilities.decide.runner.DecisionRunner``'s shape (DESIGN §1 of
lane decide-consumers) without importing ``agent_utilities`` -- the SDK must
never depend on the agent control plane (see ``pyproject.toml``'s dependency
comment) or on EG beyond its existing generated types. A process embedding
this SDK that also holds a verified EG session (for example the
``connector-sync`` runner, which already talks to EG for ``ConnectorPack``
and ``SourceIngest``) may install a real implementation that calls EG's
generated ``Decide``/``DecisionLog`` senders; with none installed, every
call site in :mod:`agent_connector_sdk.decide.consumers` is exactly its old
deterministic rule.
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
        *,
        params: Iterable[Mapping[str, Any]] = (),
        candidates: Mapping[str, Any] | None = None,
    ) -> Choice:
        """Decide from a sync call site."""
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
        """Decide from an async call site."""
        ...


__all__ = ["DecisionRunner", "Fallback"]
