"""Canonical validation for MCP listener authorities and trust networks."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from urllib.parse import urlsplit

__all__ = []

_MAX_HEADER_VALUE_BYTES = 16_384


def normalize_host_authority(raw: object) -> str:
    value = _validated_authority_value(raw)
    try:
        parsed = urlsplit(f"//{value}")
        host = str(parsed.hostname or "").rstrip(".").casefold()
        port = parsed.port
    except ValueError:
        raise ValueError("host allowlist must contain exact authorities") from None
    if not host or any(
        (
            parsed.username is not None,
            parsed.password is not None,
            bool(parsed.path),
            bool(parsed.query),
            bool(parsed.fragment),
        )
    ):
        raise ValueError("host allowlist must contain exact authorities")
    rendered = _render_host(host)
    return f"{rendered}:{port}" if port is not None else rendered


def normalize_host_authorities(authorities: Iterable[str]) -> tuple[str, ...]:
    normalized = {normalize_host_authority(raw) for raw in authorities}
    if not normalized or len(normalized) > 256:
        raise ValueError("host allowlist must contain 1..256 exact authorities")
    return tuple(sorted(normalized))


def normalize_origins(origins: Iterable[str]) -> tuple[str, ...]:
    normalized = {normalize_origin(raw) for raw in origins if str(raw or "").strip()}
    if len(normalized) > 256:
        raise ValueError("origin allowlist is too large")
    return tuple(sorted(normalized))


def normalize_cidrs(values: Iterable[str]) -> tuple[str, ...]:
    networks: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if not value:
            continue
        try:
            networks.add(ipaddress.ip_network(value, strict=True).with_prefixlen)
        except ValueError as exc:
            raise ValueError("trusted proxy CIDR is invalid") from exc
    if not networks or len(networks) > 64:
        raise ValueError("trusted proxy CIDRs must contain 1..64 exact networks")
    return tuple(sorted(networks))


def _validated_authority_value(raw: object) -> str:
    value = str(raw or "").strip()
    if (
        not value
        or len(value.encode("utf-8")) > _MAX_HEADER_VALUE_BYTES
        or any(character in value for character in "/\\@?#\r\n\t ")
        or (value.count(":") > 1 and not value.startswith("["))
    ):
        raise ValueError("host allowlist must contain exact authorities")
    return value


def normalize_origin(raw: object) -> str:
    value = str(raw).strip()
    if value == "*" or len(value) > 2_048:
        raise ValueError("origins must be exact HTTP(S) authorities")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError("origins must be exact HTTP(S) authorities") from None
    if not _valid_origin_parts(parsed):
        raise ValueError("origins must be exact HTTP(S) authorities")
    host = _render_host(str(parsed.hostname or "").lower().rstrip("."))
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    authority = host if port in {None, default_port} else f"{host}:{port}"
    return f"{parsed.scheme.lower()}://{authority}"


def _valid_origin_parts(parsed: object) -> bool:
    return all(
        (
            getattr(parsed, "scheme", "").lower() in {"http", "https"},
            bool(getattr(parsed, "hostname", None)),
            getattr(parsed, "username", None) is None,
            getattr(parsed, "password", None) is None,
            getattr(parsed, "path", None) in {"", "/"},
            not getattr(parsed, "query", None),
            not getattr(parsed, "fragment", None),
        )
    )


def _render_host(host: str) -> str:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return _render_dns_host(host)
    if isinstance(address, ipaddress.IPv6Address):
        return f"[{address.compressed}]"
    return address.compressed


def _render_dns_host(host: str) -> str:
    try:
        rendered = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("host allowlist contains an invalid name") from exc
    labels = rendered.split(".")
    if not all(
        label
        and len(label) <= 63
        and not label.startswith("-")
        and not label.endswith("-")
        and all(character.isalnum() or character == "-" for character in label)
        for label in labels
    ):
        raise ValueError("host allowlist contains an invalid name")
    return rendered
