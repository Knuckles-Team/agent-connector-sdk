"""The SDK's own consumers of EG's ``Decide`` layer (EH-041/042/043, contract
request `/var/tmp/l9/finish/decide-consumers/CONTRACT-REQUEST.md`).

Every decision point here used to be, and remains, an ad-hoc rule. It now
asks EG first and keeps that rule as the deterministic fallback::

    from agent_connector_sdk import decide
    choice = decide.choose("au.connector.tool", options, fallback=lambda: picked)

With no runner installed (no engine reachable from this process), :func:`choose`
is exactly the fallback, reason ``no_runner``. A process that also holds a
verified EG session may :func:`install_runner` a real
:class:`~agent_connector_sdk.ports.decide_runner.DecisionRunner` --
:class:`~agent_connector_sdk.decide.epistemic_graph.EpistemicGraphDecisionRunner`
is the SDK's own EG-backed one, installed at the ``connector-sync`` composition
root (:func:`agent_connector_sdk.runner.composition.default_services`) when
this process was given a tenant to decide as; tests install fakes. This
mirrors ``agent_utilities.decide``'s own contract (DESIGN.md §1 of lane
decide-consumers) so the SAME EG question is asked whichever side calls it,
but is implemented independently: the SDK never imports ``agent_utilities``
(the agent control plane) -- only the port, the EG-backed runner, and the two
evaluate-only call sites EH-042/043 name (see
:mod:`agent_connector_sdk.decide.consumers`).

EH-041 (connector inbound event triage) has no SDK-owned call site: it is
wired entirely inside ``agent_utilities`` at
``agent_utilities/knowledge_graph/adaptation/fleet_event_triage.py``, which
dispatches AU's own fleet events, not anything the SDK's connectors receive.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextvars import ContextVar
from typing import Any

from agent_connector_sdk.decide.options import (
    Option,
    declared_source,
    q32,
    text_param,
    unique_sorted,
)
from agent_connector_sdk.decide.outcome import Choice
from agent_connector_sdk.ports.decide_runner import DecisionRunner, Fallback

_RUNNER: ContextVar[DecisionRunner | None] = ContextVar(
    "agent_connector_sdk_decide_runner", default=None
)
_PROCESS: list[DecisionRunner | None] = [None]


def install_runner(runner: DecisionRunner | None) -> None:
    """Install ``runner`` for the whole process (``None`` uninstalls)."""
    _PROCESS[0] = runner


def use_runner(runner: DecisionRunner | None) -> Any:
    """Scope ``runner`` to the current context; returns the reset token."""
    return _RUNNER.set(runner)


def current_runner() -> DecisionRunner | None:
    """The context's runner, else the process runner, else ``None``."""
    return _RUNNER.get() or _PROCESS[0]


def _no_runner(fallback: Fallback) -> Choice:
    return Choice(fallback(), False, "no_runner")


#: The rest of a ``choose``/``achoose`` call (``params``, ``candidates``): kept
#: as ``**kwargs`` here, forwarded verbatim to a :class:`DecisionRunner`, so
#: this dispatcher's signature does not restate
#: :class:`~agent_connector_sdk.ports.decide_runner.DecisionRunner`'s own
#: canonical one (defined once, in ``ports/``) a second time.
def choose(
    question_id: str, options: Sequence[Option], fallback: Fallback, **kwargs: Any
) -> Choice:
    """Decide ``question_id`` from a sync call site."""
    runner = current_runner()
    if runner is None:
        return _no_runner(fallback)
    return runner.choose(question_id, options, fallback, **kwargs)


async def achoose(
    question_id: str, options: Sequence[Option], fallback: Fallback, **kwargs: Any
) -> Choice:
    """Decide ``question_id`` from an async call site."""
    runner = current_runner()
    if runner is None:
        return _no_runner(fallback)
    return await runner.achoose(question_id, options, fallback, **kwargs)


__all__ = [
    "Choice",
    "DecisionRunner",
    "Option",
    "achoose",
    "choose",
    "current_runner",
    "declared_source",
    "install_runner",
    "q32",
    "text_param",
    "unique_sorted",
    "use_runner",
]
