"""Checkpoint advancement for a source ingestion request."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from epistemic_graph.generated.source_ingestion import SourceCheckpoint
from pydantic import JsonValue

from scion_sdk.ingest.errors import IngestError
from scion_sdk.ingest.model import IngestBinding


def _prior_sequence(position: object) -> int:
    if not isinstance(position, dict):
        return 0
    sequence = position.get("sequence")
    if "sequence" in position and (
        isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0
    ):
        raise IngestError("accepted checkpoint sequence must be a non-negative integer")
    return sequence if isinstance(sequence, int) else 0


def _preserved_cursor(position: object) -> str | None:
    if not isinstance(position, dict):
        raise IngestError("accepted checkpoint position must be an object")
    prior_cursor = position.get("cursor")
    if prior_cursor is not None and not isinstance(prior_cursor, str):
        raise IngestError("accepted checkpoint cursor must be a string")
    return prior_cursor


def _checkpoint(
    binding: IngestBinding,
    previous: SourceCheckpoint | None,
    content: Iterable[Any],
    *,
    cursor: str | None = None,
    preserve_cursor: bool = False,
) -> SourceCheckpoint:
    position = previous.position if previous is not None else None
    sequence = _prior_sequence(position)
    encoded = json.dumps(
        [item.model_dump(mode="json") for item in content],
        sort_keys=True,
        separators=(",", ":"),
    )
    advanced: dict[str, JsonValue] = {
        "sequence": sequence + 1,
        "batch": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
    }
    if preserve_cursor and previous is not None:
        cursor = _preserved_cursor(position)
    if cursor is not None:
        advanced["cursor"] = cursor
    if binding.cursor_policy_iri:
        advanced["cursor_policy"] = binding.cursor_policy_iri
    return SourceCheckpoint(stream=binding.stream, position=advanced)
