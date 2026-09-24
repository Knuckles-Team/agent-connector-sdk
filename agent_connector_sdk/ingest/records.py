"""Entities derived from documents and stored media.

A document becomes a record of the binding's ``document_type`` carrying its
text and content hash; a stored media asset becomes a record of the binding's
``media_type`` carrying its Blob CAS digest.
"""

from __future__ import annotations

import hashlib

from agent_connector_sdk.ingest.errors import IngestError
from agent_connector_sdk.ingest.model import Document, Entity, IngestBinding, MediaAsset

__all__ = ["document_entity", "media_entity"]


def document_entity(binding: IngestBinding, document: Document) -> Entity:
    """The record a document becomes: its text, title, URI and content hash."""
    if not document.text:
        raise IngestError(f"document {document.id!r} has no text")
    digest = hashlib.sha256(document.text.encode("utf-8")).hexdigest()
    properties = {
        **document.properties,
        "text": document.text,
        "title": document.title,
        "source_uri": document.source_uri,
        "content_hash": digest,
    }
    return Entity(
        document.id,
        binding.document_type,
        properties,
        updated_at=document.updated_at,
        source_uri=document.source_uri,
    )


def media_entity(binding: IngestBinding, asset: MediaAsset, digest: str) -> Entity:
    """The record a stored media asset becomes; ``digest`` is its Blob CAS address."""
    properties = {
        **asset.properties,
        "blob_digest": digest,
        "mime_type": asset.mime_type,
        "size_bytes": len(asset.data),
        "name": asset.name or None,
    }
    return Entity(asset.id or f"blob:{digest}", binding.media_type, properties)
