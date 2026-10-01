"""A decision service's proposed schema repair: recorded, never activated here.

A repair proposal pairs a non-compatible :class:`~agent_connector_sdk.schema_drift.
SchemaDriftReport` with the field mapping a decision service proposes to resolve
it. Building and recording one is the whole of this module's and
:mod:`agent_connector_sdk.ports.repair_proposals`'s job (SDK-SOURCE-INGEST-R003):
a candidate graph schema, instance validation, a shadow ingest and activation are
epistemic-graph's authority alone, never constructed, run or called from here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from agent_connector_sdk.schema_drift import DriftClassification, SchemaDriftReport

__all__ = ["RepairProposal", "propose_repair"]


@dataclass(frozen=True)
class RepairProposal:
    """One proposed repair mapping for a non-compatible drift report.

    Attributes:
        report: The quarantined classification this proposal answers.
        proposed_mapping: The decision service's candidate field mapping;
            opaque to the SDK, never validated or applied here.
        proposer: Who or what proposed it (a decision-service identity),
            carried for provenance only.
    """

    report: SchemaDriftReport
    proposed_mapping: Mapping[str, Any] = field(default_factory=dict)
    proposer: str = ""

    def __post_init__(self) -> None:
        if self.report.classification is DriftClassification.COMPATIBLE:
            raise ValueError("a compatible drift report needs no repair proposal")
        if not self.proposed_mapping:
            raise ValueError("a repair proposal needs a non-empty proposed mapping")
        if not self.proposer.strip():
            raise ValueError("a repair proposal needs its proposer")


def propose_repair(
    report: SchemaDriftReport,
    proposed_mapping: Mapping[str, Any],
    *,
    proposer: str,
) -> RepairProposal:
    """Build one repair proposal for ``report``.

    Raises:
        ValueError: ``report`` is already ``COMPATIBLE``, or ``proposed_mapping``
            or ``proposer`` is empty.
    """
    return RepairProposal(
        report=report, proposed_mapping=dict(proposed_mapping), proposer=proposer
    )
