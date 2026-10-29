"""Serve a host-approved, bounded taxonomy subgraph through source ingestion."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from agent_connector_sdk._extras import require_mcp_extra
from agent_connector_sdk.ingest._stream_checkpoint import _authorize_generation
from agent_connector_sdk.ingest.live_declaration import source_meta
from agent_connector_sdk.taxonomy._graph_policy import (
    _validate_crosswalk,
    _validate_policy,
)
from agent_connector_sdk.taxonomy.provider import TaxonomyProvider, _valid_id
from agent_connector_sdk.taxonomy.records import TaxonRecord

require_mcp_extra("agent_connector_sdk.taxonomy.graph_stream")

from fastmcp import Context  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402


def _admitted_ids(
    row: TaxonRecord, crosswalk: Mapping[str, tuple[str, str]]
) -> tuple[str, str]:
    ids = crosswalk.get(row.term_curie)
    if ids is None or not all(_valid_id(value) for value in ids):
        raise ValueError("taxon crosswalk not admitted")
    ncbi, gbif = ids
    if (
        (row.ncbi_taxon_id is None and row.gbif_taxon_id is None)
        or row.ncbi_taxon_id not in (None, ncbi)
        or row.gbif_taxon_id not in (None, gbif)
    ):
        raise ValueError("crosswalk conflicts with provider identity")
    return ncbi, gbif


def _parent_edge(
    row: TaxonRecord, *, selected: set[str], roots: frozenset[str]
) -> dict[str, str] | None:
    parent = row.parent_term_curie
    if parent in (None, row.term_curie):
        if row.term_curie not in roots:
            raise ValueError("root taxon not admitted")
        return None
    if parent not in selected:
        raise ValueError("parent taxon not in bounded batch")
    return {"source": row.term_curie, "target": parent, "relationship": "parentTaxon"}


def _entities(
    rows: Sequence[TaxonRecord],
    *,
    crosswalk: Mapping[str, tuple[str, str]],
    ranks: Mapping[str, str],
    roots: frozenset[str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    selected = {row.term_curie for row in rows}
    if len(selected) != len(rows):
        raise ValueError("duplicate taxon identity")
    records: list[dict[str, Any]] = []
    relationships: list[dict[str, str]] = []
    admitted_ranks: dict[str, str] = {}
    for row in rows:
        ncbi, gbif = _admitted_ids(row, crosswalk)
        rank_id = ranks.get(row.taxon_rank or "")
        if not rank_id:
            raise ValueError("taxon rank not admitted")
        records.append(
            {
                "id": row.term_curie,
                "node_type": "Taxon",
                "scientific_name": row.scientific_name,
                "term_curie": row.term_curie,
                "ncbi_taxon_id": ncbi,
                "gbif_taxon_id": gbif,
            }
        )
        rank = f"rank:{rank_id}"
        admitted_ranks[rank] = row.taxon_rank or ""
        relationships.append(
            {"source": row.term_curie, "target": rank, "relationship": "taxonRank"}
        )
        parent = _parent_edge(row, selected=selected, roots=roots)
        if parent is not None:
            relationships.append(parent)
    records.extend(
        {"id": rank, "node_type": "TaxonRank", "name": label}
        for rank, label in sorted(admitted_ranks.items())
    )
    return records, relationships


def _binding(
    provider: TaxonomyProvider,
    ids: Sequence[str],
    *,
    tenant: str,
    name: str,
    connector: str,
    policy_revision: str,
    approved: Mapping[str, tuple[str, str]],
    rank_ids: Mapping[str, str],
    admitted_roots: frozenset[str],
    max_records: int,
) -> str:
    return hashlib.sha256(
        json.dumps(
            [
                tenant,
                name,
                connector,
                policy_revision,
                provider.provider,
                provider.http.base_url,
                ids,
                sorted(approved.items()),
                sorted(rank_ids.items()),
                sorted(admitted_roots),
                max_records,
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def register_taxonomy_graph_stream(
    server: Any,
    provider: TaxonomyProvider,
    identifiers: Sequence[str],
    *,
    tenant: str,
    name: str,
    connector: str,
    policy_revision: str,
    authorize: Callable[[str, Any], Awaitable[bool]],
    crosswalk: Mapping[str, tuple[str, str]],
    ranks: Mapping[str, str],
    roots: Sequence[str],
    max_records: int,
) -> None:
    """Publish a complete bounded subgraph under explicit host identity approvals."""
    ids = tuple(identifiers)
    approved = dict(crosswalk)
    rank_ids = dict(ranks)
    admitted_roots = frozenset(roots)
    if not all((tenant, name, connector, policy_revision)):
        raise ValueError("invalid taxonomy graph policy")
    _validate_policy(ids, max_records=max_records, ranks=rank_ids)
    _validate_crosswalk(provider.provider, ids, approved)
    if not admitted_roots.issubset(approved):
        raise ValueError("taxonomy roots not in admitted set")
    binding = _binding(
        provider,
        ids,
        tenant=tenant,
        name=name,
        connector=connector,
        policy_revision=policy_revision,
        approved=approved,
        rank_ids=rank_ids,
        admitted_roots=admitted_roots,
        max_records=max_records,
    )

    async def _serve(
        ctx: Context, mode: str, state: dict[str, Any] | None
    ) -> dict[str, Any]:
        await _authorize_generation(
            authorize,
            tenant=tenant,
            context=ctx,
            mode=mode,
            state=state,
            binding=binding,
        )
        rows = await provider.read(ids, max_records=max_records)
        records, relationships = _entities(
            rows, crosswalk=approved, ranks=rank_ids, roots=admitted_roots
        )
        return {
            "records": records,
            "relationships": relationships,
            "checkpoint": {"binding": binding, "generation": uuid.uuid4().hex},
        }

    async def taxonomy_graph_stream(
        ctx: Context, mode: str = "delta", state: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Read the complete admitted subgraph and advance its checkpoint."""
        try:
            return await _serve(ctx, mode, state)
        except Exception:
            raise ToolError("taxonomy graph page refused") from None

    metadata = source_meta(
        source_id=name,
        record_type="Taxon",
        id_field="id",
        records_path="records",
        title_field="scientific_name",
        server=connector,
        preset={
            "params_style": "args",
            "params": {"mode": "delta"},
            "record_mode": "typed_entities",
            "node_type_field": "node_type",
            "relationships_path": "relationships",
            "updated_since_param": "state",
            "checkpoint_path": "checkpoint",
        },
    )
    server.tool(name=name, annotations={"readOnlyHint": True}, meta=metadata)(
        taxonomy_graph_stream
    )
