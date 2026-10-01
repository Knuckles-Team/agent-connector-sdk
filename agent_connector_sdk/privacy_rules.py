"""Redaction rules: identifier patterns, sensitive field names, deny terms."""

from __future__ import annotations

import json
import re
import socket
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent_connector_sdk.config import setting
from agent_connector_sdk.credentials.resolution import resolve_secret_reference

__all__ = [
    "PATTERNS",
    "STRUCTURAL_ID_FIELDS",
    "field_name",
    "field_redaction",
    "runtime_deny_terms",
    "usable_terms",
]

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("tax_id", re.compile(r"\b\d{2}-\d{7}\b")),
    ("credit_card", re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    (
        "api_token",
        re.compile(
            r"(?i)\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,})\b"
        ),
    ),
    ("bearer_token", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")),
    (
        "phone",
        re.compile(
            r"(?<!\w)(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}(?!\w)"
        ),
    ),
    (
        "windows_user_path",
        re.compile(
            r"(?i)(?:[A-Z]:[\\/]|/mnt/[a-z]/)(?:Users|Documents and Settings)"
            r"[\\/][^\\/\s]+(?:[\\/][^\s]*)?"
        ),
    ),
    ("windows_absolute_path", re.compile(r"(?i)\b[A-Z]:[\\/][^\r\n\t]+")),
    ("posix_user_path", re.compile(r"(?<![\w.])/(?:home|Users)/[^/\s]+(?:/[^\s]*)?")),
    (
        "posix_local_path",
        re.compile(
            r"(?<![\w.])/(?:mnt|opt|private/tmp|root|srv|tmp|var/tmp|workspace|workspaces)"
            r"(?:/[^\s]*)?"
        ),
    ),
    ("file_uri", re.compile(r"(?i)\bfile://[^\s]+")),
    (
        "ipv4",
        re.compile(
            r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])"
        ),
    ),
    (
        "mac_address",
        re.compile(r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])"),
    ),
    ("iban", re.compile(r"(?i)\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b")),
)

_SECRET_FIELDS = frozenset(
    [
        "authorization",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "client_secret",
        "password",
        "secret",
        "token",
    ]
)
_LOCATION_FIELDS = frozenset(
    [
        "base_url",
        "canonical_url",
        "dsn",
        "endpoint",
        "endpoint_url",
        "file_path",
        "home",
        "host",
        "hostname",
        "href",
        "html_url",
        "local_path",
        "path",
        "pdf_url",
        "root_path",
        "source_uri",
        "source_url",
        "uri",
        "url",
        "web_url",
        "weburl",
        "workspace_path",
    ]
)
_PERSON_FIELDS = frozenset(
    [
        "assignee",
        "author",
        "author_name",
        "birth_date",
        "created_by",
        "date_of_birth",
        "display_name",
        "employee_id",
        "first_name",
        "full_name",
        "ip_address",
        "last_name",
        "owner",
        "owner_name",
        "person_name",
        "requester",
        "updated_by",
        "user_email",
        "user_name",
        "username",
    ]
)
_PERSON_CONTEXT = frozenset({"author", "employee", "owner", "person", "user"})
#: Opaque keys, edge endpoints and content digests: skipped by the free-text
#: pass (a hex digest can look like an IBAN), never rewritten.
STRUCTURAL_ID_FIELDS = frozenset(
    [
        "id",
        "node_id",
        "source",
        "target",
        "src",
        "dst",
        "parent",
        "agent_id",
        "run_id",
        "trace_id",
        "content_hash",
        "blob_digest",
        "digest",
    ]
)
_FIELD_REDACTIONS: tuple[tuple[frozenset[str], str, str], ...] = (
    (_SECRET_FIELDS, "secret_field", "[REDACTED_SECRET]"),
    (_LOCATION_FIELDS, "location_field", "[REDACTED_LOCATION]"),
)
_IGNORED_TERMS = frozenset(
    [
        "admin",
        "administrator",
        "cache",
        "config",
        "data",
        "home",
        "root",
        "runner",
        "system",
        "tmp",
        "user",
        "workspace",
    ]
)
_MIN_TERM = 3


def field_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def populated(item: object) -> bool:
    if item is None:
        return False
    if isinstance(item, str | dict | list | tuple | set | frozenset):
        return bool(item)
    return True


def _local_identity_terms() -> set[str]:
    candidates = {
        str(setting(name, "")).strip() for name in ("LOGNAME", "USER", "USERNAME")
    }
    candidates.add(Path.home().name.strip())
    candidates.add(socket.gethostname().strip())
    return candidates


def _policy_terms() -> list[str]:
    reference = str(setting("PERSISTENCE_PRIVACY_DENY_TERMS_REF", "")).strip()
    if not reference:
        return []
    raw = resolve_secret_reference(reference)
    try:
        value = json.loads(raw)
    except ValueError:
        value = raw.split(",")
    return (
        [term for term in value if isinstance(term, str)]
        if isinstance(value, list)
        else []
    )


def usable_terms(terms: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                term.strip()
                for term in terms
                if len(term.strip()) >= _MIN_TERM
                and term.strip().casefold() not in _IGNORED_TERMS
            }
        )
    )


@lru_cache(maxsize=1)
def runtime_deny_terms() -> tuple[str, ...]:
    """Local account/host names and the optional policy list, resolved once.

    Cached for the process: guards are built on async paths, where a secret
    lookup per call would block the event loop.
    """
    return usable_terms([*_local_identity_terms(), *_policy_terms()])


def field_redaction(
    field: str, item: Any, context: tuple[str, ...]
) -> tuple[str, str] | None:
    if not populated(item):
        return None
    for fields, label, replacement in _FIELD_REDACTIONS:
        if field in fields:
            return label, replacement
    personal = field in _PERSON_FIELDS or (
        field == "name" and any(part in _PERSON_CONTEXT for part in context)
    )
    return ("personal_field", "[REDACTED_PERSON]") if personal else None
