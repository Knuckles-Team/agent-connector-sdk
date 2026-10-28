"""Bounded schema and page validation for certified platform adapters."""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel

from agent_connector_sdk.adapters.platform_backend import (
    BackendPage,
    platform_record_schema_digest,
)
from agent_connector_sdk.adapters.platform_models import (
    PlatformCapability,
    PlatformRequest,
    PlatformResult,
    validate_request_binding,
)

_MAX_BYTES = 1_048_576


def _verify_schema(model: type[BaseModel], expected_digest: str) -> None:
    """Bind the actual validation model to the admitted schema digest."""
    if platform_record_schema_digest(model) != expected_digest:
        raise ValueError("platform output schema does not match policy")


def _validate_page(
    page: BackendPage,
    request: PlatformRequest,
    capability: PlatformCapability,
    model: type[BaseModel],
) -> tuple[BackendPage, bytes]:
    """Snapshot and validate a page and each record without exposing bad data."""
    page = BackendPage.model_validate(page.model_dump(mode="python"))
    if len(page.records) > request.limit or (
        request.operation == "read" and not page.records
    ):
        raise ValueError("invalid platform page size")
    if page.continuation is not None:
        validate_request_binding(
            request.model_copy(update={"continuation": page.continuation}), capability
        )
    canonical_page = json.dumps(
        page.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    if len(canonical_page) > _MAX_BYTES:
        raise ValueError("platform page exceeds byte limit")
    for record in page.records:
        model.model_validate(record.content, strict=True)
        canonical = json.dumps(
            record.content,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        if (
            record.provenance.content_digest
            != "sha256:" + hashlib.sha256(canonical).hexdigest()
        ):
            raise ValueError("platform content digest mismatch")
    return page, canonical_page


def _platform_request_digest(request: PlatformRequest) -> str:
    """Bind result evidence to the exact value-free digest of one request."""
    raw = json.dumps(
        request.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _bounded_json(value: object) -> str:
    encoder = json.JSONEncoder(
        ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )
    chunks: list[str] = []
    size = 0
    for chunk in encoder.iterencode(value):
        size += len(chunk.encode("utf-8"))
        if size > _MAX_BYTES + 65_536:
            raise ValueError("platform envelope exceeds the size limit")
        chunks.append(chunk)
    return "".join(chunks)


def _validate_source_binding(arguments: object, result: object) -> None:
    """Refuse a platform result that does not bind the source tool request."""
    if not isinstance(arguments, dict) or not isinstance(
        arguments.get("request"), dict
    ):
        raise ValueError("platform source request is malformed")
    request = PlatformRequest.model_validate_json(_bounded_json(arguments["request"]))
    response = PlatformResult.model_validate_json(_bounded_json(result))
    actual = (
        response.request_id,
        response.request_digest,
        response.tenant_id,
        response.principal_id,
        response.connector_id,
        response.platform_id,
        response.channel_id,
        response.operation,
    )
    expected = (
        request.request_id,
        _platform_request_digest(request),
        request.tenant_id,
        request.principal_id,
        request.connector_id,
        request.platform_id,
        request.channel_id,
        request.operation,
    )
    if actual != expected:
        raise ValueError("platform result does not bind the source request")
