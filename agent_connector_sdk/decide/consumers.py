"""EH-042 / EH-043: connector-side decisions through EG ``Decide``.

Ported from ``agent_utilities.decide.consumers.connectors`` (lane
decide-consumers, `CONTRACT-REQUEST.md` items 4/5) rather than imported: the
SDK must never depend on the agent control plane. Both are EVALUATE-ONLY
(DECIDE-LAYER-DESIGN §4.5): high-frequency, low-stakes, so a real
:class:`~agent_connector_sdk.ports.decide_runner.DecisionRunner` samples
their records into the decision log rather than committing per call, and
D18 write-back AUTHORIZATION stays deterministic -- a decision only ever
proposes.

The question ids (``au.connector.tool``, ``au.connector.writeback``) are
kept identical to ``agent_utilities``'s so a single EG-published
``FeatureSchema`` and decision log serve both AU-instrumented code and
connectors built on this SDK for the SAME logical question; only the Python
implementation is independent.

* EH-042 connector-internal tool choice: which of a connector's tools serves
  one request; the connector's own pick is the fallback.
* EH-043 write-back proposals: which candidate mutation (or none) to PROPOSE;
  the proposal still goes through the governed D18 write-back port
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


def connector_tool(connector: str, tools: Sequence[str], picked: str) -> str:
    """Which of ``tools`` serves one request (EH-042); ``picked`` is the fallback."""
    if picked not in tools:
        return picked
    choice = decide.choose(
        "au.connector.tool",
        _heuristic_options(sorted(set(tools)), picked),
        lambda: picked,
        params=[text_param("connector", connector)],
    )
    return str(choice.option_id or picked)


def propose_writeback(
    proposals: Mapping[str, Mapping[str, Any]], default: str = NO_WRITE
) -> tuple[str, Mapping[str, Any] | None]:
    """The write-back to PROPOSE (EH-043), never executed here.

    ``proposals`` maps a proposal id to its governed write-back change-set
    parameters; ``no_write`` is always an option. Returns ``(id, params)`` --
    ``params`` is ``None`` for ``no_write`` -- to hand to
    :class:`agent_connector_sdk.ports.writeback.WriteBackPort` (or an
    equivalent governed executor); D18 authorization is unchanged.
    """
    ids = sorted({*proposals, NO_WRITE})
    choice = decide.choose(
        "au.connector.writeback",
        _heuristic_options(ids, default),
        lambda: default,
    )
    chosen = str(choice.option_id or default)
    return chosen, proposals.get(chosen)


__all__ = ["NO_WRITE", "connector_tool", "propose_writeback"]
