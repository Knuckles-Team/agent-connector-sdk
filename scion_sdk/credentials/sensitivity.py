"""Which configuration keys and values may be shown on a tool surface.

Every surface that reports configuration uses this one classifier, so the
surfaces cannot disagree about what is sensitive.

* :func:`configuration_key_is_sensitive`: whether a key's value must not be
  echoed. It reads the key's own words, so an unknown key is classified
  conservatively.
* :func:`runtime_reference`: whether a value names where a secret lives
  (``vault://``, ``env://``, ``secret://`` or ``${VAR}``) rather than being
  one. A reference may be shown; only literals are redacted.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["configuration_key_is_sensitive", "runtime_reference"]

#: ``${VAR:-fallback}`` is deliberately not a reference: it embeds the value.
RUNTIME_REFERENCE_RE = re.compile(
    r"^(?:\$\{[A-Za-z_][A-Za-z0-9_]*\}|(?:vault|env|secret)://[A-Za-z0-9_./#-]+)$"
)

_SENSITIVE_PARTS = frozenset(
    {
        "authorization",
        "credential",
        "credentials",
        "email",
        "identity",
        "password",
        "secret",
        "tenant",
        "token",
        "user",
        "username",
    }
)
_ENDPOINT_PARTS = frozenset(
    {
        "address",
        "baseurl",
        "broker",
        "brokers",
        "endpoint",
        "endpoints",
        "host",
        "hostname",
        "hosts",
        "server",
        "servers",
        "uri",
        "uris",
        "url",
        "urls",
    }
)
_PATH_PARTS = frozenset(
    {
        "bundle",
        "ca",
        "cert",
        "certificate",
        "cwd",
        "directory",
        "dir",
        "file",
        "keyfile",
        "path",
        "root",
        "workspace",
    }
)
_ID_OWNERS = frozenset({"actor", "agent", "client", "identity", "tenant", "user"})
_KEY_OWNERS = frozenset(
    {"api", "auth", "client", "encryption", "hmac", "private", "signing", "tls"}
)


def normalised_key_parts(key: str) -> set[str]:
    """Lower-cased word set of a key, for camelCase and snake_case alike."""
    normalised = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key).lower()
    parts = {part for part in re.split(r"[^a-z0-9]+", normalised) if part}
    if {"base", "url"} <= parts:
        parts.add("baseurl")
    if {"key", "file"} <= parts:
        parts.add("keyfile")
    return parts


def configuration_key_is_sensitive(
    env_key: str, metadata: dict[str, Any] | None = None
) -> bool:
    """Whether the value of ``env_key`` must not cross a tool surface."""
    if (metadata or {}).get("secret"):
        return True
    parts = normalised_key_parts(env_key)
    if parts & (_SENSITIVE_PARTS | _ENDPOINT_PARTS | _PATH_PARTS):
        return True
    if env_key.upper() == "MCP_CONFIG":
        return True
    if "id" in parts and parts & _ID_OWNERS:
        return True
    return "key" in parts and bool(parts & _KEY_OWNERS)


def runtime_reference(value: Any) -> bool:
    """Whether ``value`` is a non-literal runtime reference."""
    return isinstance(value, str) and bool(RUNTIME_REFERENCE_RE.fullmatch(value))
