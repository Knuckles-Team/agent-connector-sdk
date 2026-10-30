"""Connection-profile parsing for the database document source."""

from __future__ import annotations

import json
from typing import Any, cast

_DATABASE_PROFILE_FIELDS = frozenset(
    {"dsn", "kind", "tls_service", "tls_profile", "tls_profile_ref"}
)


def _render_connection_profile(raw: object) -> str:
    rendered = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw or "")
    if not rendered or len(rendered.encode("utf-8")) > 65_536:
        raise ValueError("database connection profile is unavailable")
    return rendered


def _load_connection_profile(rendered: str) -> dict[str, Any] | None:
    try:
        profile = json.loads(rendered)
    except (TypeError, ValueError):
        return None
    if not isinstance(profile, dict):
        return None
    if set(profile).difference(_DATABASE_PROFILE_FIELDS):
        raise ValueError("database connection profile has unsupported fields")
    return profile


def _validate_profile_dsn(resolved_dsn: str) -> None:
    if not resolved_dsn:
        raise ValueError("database connection profile is unavailable")
    if "\x00" in resolved_dsn:
        raise ValueError("database connection profile is unavailable")
    if len(resolved_dsn.encode("utf-8")) > 8_192:
        raise ValueError("database connection profile is unavailable")


def _profile_tls_values(
    profile: dict[str, Any] | None,
) -> tuple[str | None, str | None, str | None]:
    profile = profile or {}
    return cast(
        tuple[str | None, str | None, str | None],
        tuple(
            str(profile.get(key) or "").strip() or None
            for key in ("tls_service", "tls_profile", "tls_profile_ref")
        ),
    )


def _parse_connection_profile(
    rendered: str,
) -> tuple[str, str | None, tuple[str | None, str | None, str | None]]:
    profile = _load_connection_profile(rendered)
    if profile is None:
        resolved_dsn, profile_kind = rendered, None
    else:
        resolved_dsn = str(profile.get("dsn") or "")
        profile_kind = str(profile.get("kind") or "").strip().lower() or None
    _validate_profile_dsn(resolved_dsn)
    return resolved_dsn, profile_kind, _profile_tls_values(profile)
