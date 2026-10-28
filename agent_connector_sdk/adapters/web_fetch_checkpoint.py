"""Validate the legacy fixed-list web-fetch checkpoint."""

from __future__ import annotations

from epistemic_graph.generated.source_ingestion import SourceCheckpoint

from agent_connector_sdk.ports.errors import SourceContractError


def _page_index(
    checkpoint: SourceCheckpoint | None, stream: str, *, count: int, url_digest: str
) -> int:
    """Return an in-range index or refuse the checkpoint before fetching."""
    if checkpoint is None:
        return 0
    index = checkpoint.position.get("index")
    if checkpoint.stream != stream or type(index) is not int or not 0 <= index <= count:
        raise SourceContractError("invalid web fetch checkpoint")
    _verify_url_digest(checkpoint, url_digest)
    return index


def _verify_url_digest(checkpoint: SourceCheckpoint, url_digest: str) -> None:
    if (
        "url_list_sha256" in checkpoint.position
        and checkpoint.position["url_list_sha256"] != url_digest
    ):
        raise SourceContractError("web fetch checkpoint does not match URL list")


def _next_checkpoint(
    checkpoint: SourceCheckpoint | None,
    stream: str,
    *,
    index: int,
    next_index: int,
    url_digest: str,
) -> SourceCheckpoint:
    if checkpoint is not None and index == next_index:
        return checkpoint
    return SourceCheckpoint(
        stream=stream, position={"index": next_index, "url_list_sha256": url_digest}
    )
