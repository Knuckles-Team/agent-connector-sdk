"""Shared constants and types for the fail-closed source HTTP boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_REQUEST_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_REDIRECTS = 3
HARD_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
HARD_MAX_REDIRECTS = 10
_HARD_MAX_TIMEOUT_SECONDS = 300.0
_HARD_MAX_URL_CHARS = 8_192
_HARD_MAX_REQUEST_HEADERS = 64
_HARD_MAX_REQUEST_HEADER_BYTES = 64 * 1024
_HARD_MAX_QUERY_PARAMETERS = 128
_METADATA_ADDRESSES = frozenset({"169.254.169.254", "fd00:ec2::254"})
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_SENSITIVE_REDIRECT_HEADERS = frozenset(
    {"authorization", "cookie", "proxy-authorization"}
)
_FORBIDDEN_CALLER_HEADERS = frozenset(
    {
        "connection",
        "content-length",
        "host",
        "proxy-authorization",
        "proxy-connection",
        "te",  # codespell:ignore te
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)


class SourceEgressError(ValueError):
    """A source URL violated the connector egress policy."""


@dataclass(frozen=True, slots=True)
class ResolvedSourceURL:
    """One logical source URL and the exact addresses approved for this hop."""

    url: str
    host: str
    scheme: str
    resolved_ips: tuple[str, ...]

    @property
    def pinned_ip(self) -> str:
        """Select one resolver-ordered address; the client never resolves again."""
        return self.resolved_ips[0]


@dataclass(frozen=True, slots=True)
class _PinnedProxy:
    url: str
    scheme: str


def _reject_unknown_options(options: Mapping[str, Any], schema: type) -> None:
    """Reject keyword options that are not declared by a TypedDict ``schema``."""
    unexpected = sorted(set(options) - set(schema.__annotations__))
    if unexpected:
        raise TypeError(f"unexpected keyword argument {unexpected[0]!r}")


def _require_byte_limit(name: str, value: int) -> None:
    if not 1 <= value <= HARD_MAX_RESPONSE_BYTES:
        raise ValueError(f"{name} must be between 1 and {HARD_MAX_RESPONSE_BYTES}")
