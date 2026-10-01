"""Where a proposed schema repair is recorded and a stream's pause is read.

Recording and pause-reading are the entire boundary: no method here
constructs a candidate graph schema, validates instances, performs a shadow
ingest, or activates a repair -- those are epistemic-graph's authority alone
(SDK-SOURCE-INGEST-R003).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_connector_sdk.schema_repair import RepairProposal

__all__ = ["RepairProposalStore"]


@runtime_checkable
class RepairProposalStore(Protocol):
    """Record proposals and answer whether a stream is paused on one."""

    async def record(self, proposal: RepairProposal) -> None:
        """Durably record ``proposal``; never activates or mutates a schema."""
        ...

    async def paused(self, source: str, stream: str) -> bool:
        """Whether ``source``/``stream`` has an unresolved repair proposal."""
        ...
