"""URL shape, hostname and origin validation for the source HTTP boundary."""

from __future__ import annotations

import ipaddress
import math
from urllib.parse import SplitResult, urlsplit, urlunsplit

from ._http_types import (
    _HARD_MAX_TIMEOUT_SECONDS,
    _HARD_MAX_URL_CHARS,
    SourceEgressError,
)


def _idna_encode(candidate: str) -> str:
    try:
        return candidate.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise SourceEgressError(
            "Source hostname is not permitted by egress policy"
        ) from exc


def _validate_idna_labels(rendered: str) -> None:
    labels = rendered.split(".")
    if (
        len(rendered) > 253
        or any(not label or len(label) > 63 for label in labels)
        or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789-._"
            for character in rendered
        )
    ):
        raise SourceEgressError("Source hostname is not permitted by egress policy")


def _normalize_hostname(value: str) -> str:
    candidate = value.strip().lower().rstrip(".")
    if not candidate or "%" in candidate:
        raise SourceEgressError("Source hostname is not permitted by egress policy")
    try:
        return ipaddress.ip_address(candidate).compressed
    except ValueError:
        pass
    rendered = _idna_encode(candidate)
    _validate_idna_labels(rendered)
    return rendered


def _validate_url_characters(url: str) -> None:
    if (
        not isinstance(url, str)
        or not url
        or len(url) > _HARD_MAX_URL_CHARS
        or "\\" in url
        or any(ord(character) < 32 or ord(character) == 127 for character in url)
    ):
        raise SourceEgressError("Source URL is not permitted by egress policy")


def _validate_url_port(parsed: SplitResult) -> None:
    try:
        port = parsed.port
    except ValueError as exc:
        raise SourceEgressError("Source URL is not permitted by egress policy") from exc
    if port == 0:
        raise SourceEgressError("Source URL is not permitted by egress policy")


def _validate_url_shape(url: str) -> SplitResult:
    _validate_url_characters(url)
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.fragment:
        raise SourceEgressError("Source URL is not permitted by egress policy")
    _normalize_hostname(parsed.hostname)
    if parsed.username is not None or parsed.password is not None:
        raise SourceEgressError("Source URL is not permitted by egress policy")
    _validate_url_port(parsed)
    return parsed


def _validate_timeout(timeout: float) -> float:
    if isinstance(timeout, bool):
        raise ValueError("timeout must be a finite positive number")
    try:
        value = float(timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout must be a finite positive number") from exc
    if not math.isfinite(value) or not 0 < value <= _HARD_MAX_TIMEOUT_SECONDS:
        raise ValueError(
            f"timeout must be greater than 0 and at most {_HARD_MAX_TIMEOUT_SECONDS}"
        )
    return value


def _pinned_url(logical_url: str, ip: str) -> str:
    parsed = _validate_url_shape(logical_url)
    address = ipaddress.ip_address(ip)
    host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit((parsed.scheme, f"{host}{port}", parsed.path, parsed.query, ""))


def _logical_authority(logical_url: str) -> str:
    parsed = _validate_url_shape(logical_url)
    host = _normalize_hostname(parsed.hostname or "")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        rendered_host = host
    else:
        rendered_host = f"[{address.compressed}]" if address.version == 6 else host
    return (
        f"{rendered_host}:{parsed.port}" if parsed.port is not None else rendered_host
    )


def _logical_origin(logical_url: str) -> tuple[str, str, int]:
    parsed = _validate_url_shape(logical_url)
    return (
        parsed.scheme,
        _normalize_hostname(parsed.hostname or ""),
        parsed.port or (443 if parsed.scheme == "https" else 80),
    )
