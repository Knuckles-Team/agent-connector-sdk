"""An in-memory :class:`~agent_connector_sdk.ports.repair_proposals.RepairProposalStore`."""

from __future__ import annotations

from agent_connector_sdk.schema_repair import RepairProposal

__all__ = ["InMemoryRepairProposalStore"]


class InMemoryRepairProposalStore:
    """Keep proposals in memory, keyed by source/stream; one proposal pauses it."""

    def __init__(self) -> None:
        self.proposals: dict[tuple[str, str], RepairProposal] = {}

    async def record(self, proposal: RepairProposal) -> None:
        """Record ``proposal``, replacing any earlier one for the same stream."""
        report = proposal.report
        self.proposals[report.source, report.stream] = proposal

    async def paused(self, source: str, stream: str) -> bool:
        """Whether ``source``/``stream`` has an unresolved recorded proposal."""
        return (source, stream) in self.proposals

    def resolve(self, source: str, stream: str) -> None:
        """Test/ops helper: clear a proposal once epistemic-graph resolves it."""
        self.proposals.pop((source, stream), None)
