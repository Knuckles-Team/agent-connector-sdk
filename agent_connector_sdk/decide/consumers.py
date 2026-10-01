"""Connector-side decisions through EG ``Decide`` (SDK-CONNECTOR-CONTROL-R006,
SDK-GOVERNED-WRITEBACK-R001).

Ported from agent-utilities' equivalent connector decision consumers rather
than imported: the SDK must never depend on the agent control plane. All
three call sites are EVALUATE-ONLY: high-frequency, low-stakes, so a real
:class:`~agent_connector_sdk.ports.decide_runner.DecisionRunner` samples
their records into the decision log rather than committing per call, and
write-back authorization stays deterministic -- a decision only ever
proposes, never applies.

The question ids (``au.connector.tool``, ``au.connector.writeback``,
``au.connector.triage``) are kept identical to ``agent_utilities``'s so a
single EG-published ``FeatureSchema`` and decision log serve both
AU-instrumented code and connectors built on this SDK for the SAME logical
question; only the Python implementation is independent.

* Connector-internal tool choice: which of a connector's tools serves one
  request; the connector's own pick is the fallback.
* Inbound event triage: which named action handles one batch of inbound
  connector change events (for example a ``subscriptions/listen`` delivery);
  the connector's own deterministic read of the batch is the fallback and
  the only candidates ever offered, so a proposal here can never ask for an
  action the deterministic rule did not already name.
* Write-back proposals: which candidate mutation (or none) to PROPOSE; the
  proposal still goes through the governed write-back port
  (:mod:`agent_connector_sdk.writeback`) -- authorization, versioning,
  reconciliation -- before anything is written.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from agent_connector_sdk import decide
from agent_connector_sdk.decide.options import Option, text_param

NO_WRITE = "no_write"


def _heuristic_options(
    ids: Sequence[str], pick: str, **numbers: Mapping[str, float]
) -> list[Option]:
    return [
        Option(
            i,
            {
                "heuristic": 1.0 if i == pick else 0.0,
                **{k: v[i] for k, v in numbers.items()},
            },
        )
        for i in ids
    ]


def _bounded_choice(
    question_id: str, connector: str, candidates: Sequence[str], picked: str
) -> str:
    """Confirm or redirect ``picked`` among ``candidates``, never outside them.

    A pick outside ``candidates`` is a caller bug, not a decision: EG is
    never asked about it, and it stays the fallback.
    """
    if picked not in candidates:
        return picked
    choice = decide.choose(
        question_id,
        _heuristic_options(sorted(set(candidates)), picked),
        lambda: picked,
        params=[text_param("connector", connector)],
    )
    return str(choice.option_id or picked)


def connector_tool(connector: str, tools: Sequence[str], picked: str) -> str:
    """Which of ``tools`` serves one request; ``picked`` is the fallback."""
    return _bounded_choice("au.connector.tool", connector, tools, picked)


def triage_event(connector: str, actions: Sequence[str], picked: str) -> str:
    """Which named action handles one inbound connector change-event batch.

    ``picked`` -- the connector's own deterministic read of the batch (for
    example ``agent_connector_sdk.runner.plans.change_plan``'s classification
    of it) -- is both the fallback and the only pick ever honored outside
    ``actions``. Nothing here calls the write-back port or any other
    side-effecting API -- a call site still executes exactly the action
    returned, through its own ordinary (non-write-back) path.
    """
    return _bounded_choice("au.connector.triage", connector, actions, picked)


def propose_writeback(
    proposals: Mapping[str, Mapping[str, Any]], default: str = NO_WRITE
) -> tuple[str, Mapping[str, Any] | None]:
    """The write-back to PROPOSE, never executed here.

    ``proposals`` maps a proposal id to its governed write-back change-set
    parameters; ``no_write`` is always an option. Returns ``(id, params)`` --
    ``params`` is ``None`` for ``no_write`` -- to hand to
    :class:`agent_connector_sdk.ports.writeback.WriteBackPort` (or an
    equivalent governed executor); write-back authorization is unchanged.
    """
    ids = sorted({*proposals, NO_WRITE})
    choice = decide.choose(
        "au.connector.writeback",
        _heuristic_options(ids, default),
        lambda: default,
    )
    chosen = str(choice.option_id or default)
    return chosen, proposals.get(chosen)


__all__ = ["NO_WRITE", "connector_tool", "propose_writeback", "triage_event"]
