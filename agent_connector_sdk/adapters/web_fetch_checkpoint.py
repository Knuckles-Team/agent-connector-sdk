"""Validate the legacy fixed-list web-fetch checkpoint."""

from __future__ import annotations

from epistemic_graph.generated.source_ingestion import SourceCheckpoint

from agent_connector_sdk.ports.errors import SourceContractError


def _page_index(checkpoint: SourceCheckpoint | None, stream: str, count: int) -> int:
    """Return an in-range index or refuse the checkpoint before fetching."""
    if checkpoint is None:
        return 0
    index = checkpoint.position.get("index")
    if checkpoint.stream != stream or type(index) is not int or not 0 <= index <= count:
        raise SourceContractError("invalid web fetch checkpoint")
    return index
