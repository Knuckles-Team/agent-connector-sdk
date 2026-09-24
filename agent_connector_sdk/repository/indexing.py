"""Bounded, one-call branch-aware repository indexing through the public EG client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from epistemic_graph.client import EpistemicGraphClient
from epistemic_graph.generated.index_repository import (
    IndexRepositoryScope,
    IndexResult,
)

from agent_connector_sdk.repository.batching import RepositoryBatch
from agent_connector_sdk.repository.errors import RepositoryTransportError
from agent_connector_sdk.repository.models import RepositoryFile

__all__ = ["RepositoryBatchReceipt"]

_STATUSES = frozenset({"success", "unsupported", "error"})


@dataclass(frozen=True)
class RepositoryBatchReceipt:
    """The submitted blob paths, membership counts and native EG result of one call."""

    paths: tuple[str, ...]
    file_versions: int
    tombstones: int
    result: IndexResult


@dataclass(frozen=True)
class ScopeHeader:
    """The per-run part of every batch: target graph, repository and refs."""

    graph: str | None
    repository_id: str
    refs: tuple[dict[str, str], ...]


def _status_value(status: object) -> str:
    value = getattr(status, "value", status)
    if not isinstance(value, str):
        raise RepositoryTransportError("index outcome status is not a string enum")
    return value


def _valid_digest(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    payload = value.removeprefix("sha256:")
    return len(payload) == 64 and all(char in "0123456789abcdef" for char in payload)


def _validate_outcomes(result: IndexResult, files: list[RepositoryFile]) -> None:
    outcomes = result.file_outcomes
    if len(outcomes) != len(files):
        raise RepositoryTransportError(
            "epistemic-graph returned incomplete file outcomes"
        )
    for outcome, source in zip(outcomes, files, strict=True):
        if outcome.file_path != source.path:
            raise RepositoryTransportError("epistemic-graph reordered file outcomes")
        if outcome.content_digest != source.blob_digest:
            raise RepositoryTransportError("epistemic-graph outcome digest mismatch")
        if _status_value(outcome.status) not in _STATUSES:
            raise RepositoryTransportError(
                "epistemic-graph returned unknown parse status"
            )
        if not _valid_digest(outcome.parser_capability_digest):
            raise RepositoryTransportError("parser capability digest is invalid")


def _scope(header: ScopeHeader, batch: RepositoryBatch) -> IndexRepositoryScope:
    payload: dict[str, Any] = {
        "repository_id": header.repository_id,
        "refs": list(header.refs),
        "file_versions": [
            {"ref_name": ref_name, "path": path, "blob_digest": digest}
            for ref_name, path, digest in batch.versions
        ],
        "tombstones": [
            {"ref_name": ref_name, **tombstone.model_dump(mode="json")}
            for ref_name, tombstone in batch.tombstones
        ],
    }
    return IndexRepositoryScope.model_validate(payload)


async def submit_repository_batch(
    client: EpistemicGraphClient, header: ScopeHeader, batch: RepositoryBatch
) -> RepositoryBatchReceipt:
    """Make the sole high-level EG call for one batch and validate outcomes."""
    payload = [(item.path, item.content) for item in batch.files]
    result = await client.graph.index_repository(
        payload, scope=_scope(header, batch), graph=header.graph
    )
    _validate_outcomes(result, batch.files)
    return RepositoryBatchReceipt(
        paths=tuple(item.path for item in batch.files),
        file_versions=len(batch.versions),
        tombstones=len(batch.tombstones),
        result=result,
    )
