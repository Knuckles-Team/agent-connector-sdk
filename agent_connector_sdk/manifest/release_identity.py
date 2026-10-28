"""Canonical identity for a live declaration and its ontology graph.

This digest is not a signature or an admission decision. The caller must bind
it to a trusted signer before relying on it as release integrity evidence.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

if TYPE_CHECKING:
    from rdflib import Graph

    from agent_connector_sdk.ingest.sources import IngestSourceDeclaration

__all__ = ["release_identity_digest"]


def _require_string_keys(value: Any) -> None:
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("declaration object keys must be strings")
        for item in value.values():
            _require_string_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _require_string_keys(item)


def _validated_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    from agent_connector_sdk.ingest.sources import IngestSourceDeclaration

    try:
        return IngestSourceDeclaration.model_validate(payload).model_dump(mode="python")
    except ValidationError:
        raise ValueError("release declaration is invalid") from None


def release_identity_digest(declaration: IngestSourceDeclaration, graph: Graph) -> str:
    """Hash a validated declaration and RDF graph as a domain-separated pair.

    Mapping order and RDF triple order do not affect the result. Ordered arrays
    retain their order. Blank nodes use RDFLib's canonical graph labels.
    """
    from rdflib.compare import to_canonical_graph

    payload = declaration.model_dump(mode="python", warnings=False)
    _require_string_keys(payload)
    # Nested declaration values remain mutable after Pydantic construction.
    # Hash only a newly validated snapshot of the current complete declaration.
    payload = _validated_snapshot(payload)
    document = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    canonical_graph = to_canonical_graph(graph)
    triples = sorted(f"{s.n3()} {p.n3()} {o.n3()} ." for s, p, o in canonical_graph)
    graph_bytes = "\n".join(triples).encode("utf-8")
    declaration_hash = hashlib.sha256(document).digest()
    graph_hash = hashlib.sha256(graph_bytes).digest()
    return hashlib.sha256(
        b"scion-release-identity-v1\0" + declaration_hash + graph_hash
    ).hexdigest()
