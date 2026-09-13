"""Redact credentials from URLs and headers before they reach a log."""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

__all__ = ["REDACTED", "is_sensitive_name", "redact_headers", "redact_url"]

#: The replacement for a redacted value.
REDACTED = "REDACTED"

_SENSITIVE_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "cookie", "set-cookie"}
)
_SENSITIVE_NAME_RE = re.compile(
    r"token|secret|passw|api[-_]?key|apikey|auth|signature|sig$|credential|session|^code$|^key$",
    re.IGNORECASE,
)


def is_sensitive_name(name: str) -> bool:
    """Whether a header or query parameter name is likely to carry a credential."""
    lowered = name.strip().lower()
    return (
        lowered in _SENSITIVE_HEADERS or _SENSITIVE_NAME_RE.search(lowered) is not None
    )


def redact_headers(headers: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Headers with every sensitive value replaced by :data:`REDACTED`.

    Accepts ``dict.items()`` or ``httpx.Headers.multi_items()``.
    """
    return {
        name: REDACTED if is_sensitive_name(name) else value for name, value in headers
    }


def redact_url(url: object) -> str:
    """The URL without user information and with sensitive query values redacted."""
    parts = urlsplit(str(url))
    host = parts.hostname or ""
    netloc = f"[{host}]" if ":" in host else host
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    query = urlencode(
        [
            (name, REDACTED if is_sensitive_name(name) else value)
            for name, value in parse_qsl(parts.query, keep_blank_values=True)
        ]
    )
    return urlunsplit((parts.scheme, netloc, parts.path, query, ""))
