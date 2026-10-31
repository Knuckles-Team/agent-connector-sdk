"""Configuration coercion helpers for the GraphQL document connector."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from scion_sdk.privacy import PersistencePrivacyGuard

from ..base import (
    ExternalAccess,
)
from ._graphql_base import (
    GraphQLDocumentError,
)


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _cfg_int(config: Mapping[str, Any], key: str, default: int) -> int:
    return int(config.get(key) or default)


def _cfg_float(config: Mapping[str, Any], key: str, default: float) -> float:
    return float(config.get(key) or default)


def _parse_configured_tls_mapping(
    configured: Mapping[str, Any],
) -> tuple[str | None, str | None, Mapping[str, Any] | None]:
    profile_name = (
        str(configured.get("profile_name") or configured.get("profile") or "").strip()
        or None
    )
    profile_ref = str(configured.get("profile_ref") or "").strip() or None
    settings = configured.get("settings")
    inline: Mapping[str, Any] | None = None
    if isinstance(settings, Mapping):
        inline = settings
    elif not profile_name and not profile_ref:
        inline = configured
    return profile_name, profile_ref, inline


def _parse_configured_tls(
    configured: Any,
) -> tuple[str | None, str | None, Mapping[str, Any] | None]:
    if isinstance(configured, str):
        return configured, None, None
    if isinstance(configured, Mapping):
        return _parse_configured_tls_mapping(configured)
    if configured is not None:
        raise GraphQLDocumentError("GraphQL transport security profile is invalid")
    return None, None, None


def _access_from_config(value: Any) -> ExternalAccess:
    if value is None:
        return ExternalAccess.quarantined()
    access = ExternalAccess.model_validate(value)
    if access.user_emails:
        raise ValueError(
            "GraphQL document ingestion does not persist user-email ACLs; "
            "use non-personal group aliases or a mandatory marking"
        )
    guard = PersistencePrivacyGuard()
    if any(
        guard.sanitize_text(str(principal))[1].changed
        for principal in (*access.group_ids, *access.markings)
    ):
        raise ValueError("GraphQL ACL aliases must be non-personal and location-free")
    if not access.is_public and not (access.group_ids or access.markings):
        return ExternalAccess.quarantined()
    return access
