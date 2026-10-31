"""Digest, alias and governance value helpers for the GraphQL document connector."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any

from scion_sdk.data_prep._classification import DataClassification

from ..base import (
    ExternalAccess,
)
from ._graphql_base import (
    _ALIAS_RE,
    _DOCUMENT_TYPE_RE,
    GraphQLDocumentError,
)


def _digest(*parts: Any) -> str:
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _private_digest(key: str, *parts: Any) -> str:
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return hmac.new(
        key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _safe_alias(value: str, *, label: str) -> str:
    clean = str(value or "").strip().lower()
    if not _ALIAS_RE.fullmatch(clean):
        raise ValueError(f"{label} must be a neutral lowercase alias")
    return clean


def _safe_document_type(value: Any) -> str:
    clean = str(value or "external_document").strip().lower()
    return clean if _DOCUMENT_TYPE_RE.fullmatch(clean) else "external_document"


def _safe_entity_type(value: Any, *, fallback: str) -> str:
    clean = str(value or fallback).strip()
    return clean if re.fullmatch(r"^[A-Za-z][A-Za-z0-9_-]{1,63}$", clean) else fallback


def _classification(value: Any) -> DataClassification:
    try:
        return DataClassification(str(value or DataClassification.INTERNAL.value))
    except ValueError:
        raise GraphQLDocumentError(
            "GraphQL governance classification is invalid"
        ) from None


def _policy_values(
    value: Any, *, label: str, pattern: re.Pattern[str]
) -> tuple[str, ...]:
    if value in (None, []):
        return ()
    if not isinstance(value, list) or not value or len(value) > 256:
        raise GraphQLDocumentError(f"GraphQL {label} allowlist is invalid")
    result = tuple(str(item).strip() for item in value)
    if any(
        len(item.encode("utf-8")) > 512 or not pattern.fullmatch(item)
        for item in result
    ):
        raise GraphQLDocumentError(f"GraphQL {label} allowlist is invalid")
    return result


def _validate_governance_classification(
    classification: DataClassification, access: ExternalAccess
) -> None:
    if classification == DataClassification.PUBLIC and not access.is_public:
        raise GraphQLDocumentError(
            "GraphQL public classification requires public source access"
        )
    if classification != DataClassification.PUBLIC and access.is_public:
        raise GraphQLDocumentError(
            "GraphQL non-public classification cannot use public source access"
        )
