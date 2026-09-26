"""Connector configuration: the one sanctioned environment accessor.

Extracted from ``agent_utilities.core._env.setting`` and the connector-relevant
part of ``agent_utilities.core.config.load_config``. The agent-plane parts of
AU's ``AgentConfig`` (model registries, messaging, engine topology, retired-key
migration) stay behind.

Rules this module enforces:

* Connector code reads process configuration only through :func:`setting`.
* :func:`load_config` projects one JSON document into the process environment;
  an explicitly set environment variable always wins over the file.
* A credential-shaped key (``*_SECRET``, ``*_PASSWORD``, ``*_TOKEN``,
  ``*_API_KEY``, ``*_PRIVATE_KEY``) in the file must hold a secret *reference*
  (``env://`` or ``openbao://``), never a value. References are resolved at the
  composition root through :mod:`agent_connector_sdk.credentials`.
"""

from __future__ import annotations

import ipaddress
import json
import os
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from agent_connector_sdk.utilities import to_boolean, to_dict, to_list

__all__ = [
    "CONFIG_FILE_SETTING",
    "ConfigurationError",
    "config_file_path",
    "csv_values",
    "load_config",
    "normalize_http_host_allowlist",
    "setting",
    "validate_discovery_limit",
    "validate_http_base_url",
    "validate_ingest_budget",
    "validate_ingest_limit",
]

#: Environment variable naming an explicit configuration document.
CONFIG_FILE_SETTING = "CONNECTOR_CONFIG_FILE"

_CREDENTIAL_SUFFIXES = ("_SECRET", "_PASSWORD", "_TOKEN", "_API_KEY", "_PRIVATE_KEY")
_REFERENCE_SCHEMES = ("env://", "openbao://")
_MAX_CONFIG_BYTES = 1024 * 1024
_MAX_VALUE_BYTES = 32 * 1024
# Order matters: bool is a subclass of int.
_CASTS: tuple[tuple[type, Callable[[str], Any]], ...] = (
    (bool, to_boolean),
    (int, int),
    (float, float),
    (list, to_list),
    (dict, to_dict),
)

_load_lock = threading.Lock()
_loaded_from: Path | None = None


class ConfigurationError(RuntimeError):
    """The configuration document is unreadable or violates the secret policy.

    Messages name the offending key but never its value.
    """


def validate_http_base_url(value: object) -> str | None:
    """Validate a bounded HTTP base URL without resolving or fetching it."""
    if value in (None, ""):
        return None
    rendered = str(value).strip()
    if not rendered:
        return None
    if len(rendered) > 2_048 or any(char.isspace() for char in rendered):
        raise ValueError(
            "runtime HTTP endpoints must be bounded URLs without whitespace"
        )
    if "{" in rendered or "}" in rendered:
        raise ValueError("runtime HTTP endpoints cannot contain placeholders")
    try:
        parsed = urlsplit(rendered)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("runtime HTTP endpoint is malformed") from exc
    if scheme not in {"http", "https"} or not parsed.netloc or not hostname:
        raise ValueError("runtime HTTP endpoints must use http:// or https://")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("runtime HTTP endpoints cannot contain inline credentials")
    if parsed.query or parsed.fragment:
        raise ValueError(
            "runtime HTTP base URLs cannot contain query strings or fragments"
        )
    if port is not None and not 1 <= port <= 65_535:
        raise ValueError("runtime HTTP endpoint port is out of range")
    return f"{scheme}{rendered[len(parsed.scheme) :]}".rstrip("/")


_INGEST_LIMITS = {
    "ingest_max_records": (1, 10_000),
    "ingest_page_size": (1, 1_000),
    "ingest_max_pages": (1, 1_000),
    "ingest_max_row_bytes": (256, 8_388_608),
    "ingest_max_total_bytes": (256, 67_108_864),
    "ingest_max_nesting_depth": (1, 64),
    "ingest_max_collection_items": (1, 100_000),
}

_DISCOVERY_LIMITS = {
    "discovery_max_types": (1, 500),
    "discovery_max_depth": (1, 12),
}


def _validate_integer_limit(
    name: str, value: object, limits: Mapping[str, tuple[int, int]]
) -> int:
    lower, upper = limits[name]
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{name} must be an integer")
    if isinstance(value, str) and not value.strip().isdecimal():
        raise ValueError(f"{name} must be an integer")
    parsed = int(value)
    if not lower <= parsed <= upper:
        raise ValueError(f"{name} must be between {lower} and {upper}")
    return parsed


def validate_discovery_limit(name: str, value: object) -> int:
    """Validate a connector schema discovery breadth or depth limit."""
    return _validate_integer_limit(name, value, _DISCOVERY_LIMITS)


def validate_ingest_limit(name: str, value: object) -> int:
    """Validate one bounded connector ingestion limit.

    Booleans are rejected even though Python treats them as integers. Unknown
    limit names are programmer errors and never silently acquire a default.
    """
    return _validate_integer_limit(name, value, _INGEST_LIMITS)


def validate_ingest_budget(row_bytes: int, total_bytes: int) -> None:
    """Require the cumulative transfer budget to hold at least one row."""
    if total_bytes < row_bytes:
        raise ValueError("ingest_max_total_bytes must cover one bounded row")


def normalize_http_host_allowlist(hosts: list[str]) -> list[str]:
    """Validate exact outbound host exceptions and return a stable set.

    An exception names one IP address or DNS hostname. Wildcards, URL syntax,
    Unicode names, and empty labels never enlarge the egress boundary.
    """
    if len(hosts) > 256:
        raise ValueError("HTTP host allow-lists may contain at most 256 entries")
    normalized: set[str] = set()
    for raw in hosts:
        host = str(raw).strip().lower().rstrip(".")
        _validate_exact_http_host(host)
        normalized.add(host)
    return sorted(normalized)


def _validate_exact_http_host(host: str) -> None:
    try:
        host.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("HTTP host allow-lists require ASCII hostnames") from exc
    if (
        not host
        or len(host) > 253
        or any(ord(character) < 33 for character in host)
        or any(character in host for character in "/@*?#[]")
    ):
        raise ValueError("HTTP host allow-lists require exact hostnames")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        labels = host.split(".")
        if not all(_valid_dns_label(label) for label in labels):
            raise ValueError("HTTP host allow-lists require exact hostnames") from None


def _valid_dns_label(label: str) -> bool:
    return bool(
        label
        and len(label) <= 63
        and not label.startswith("-")
        and not label.endswith("-")
        and all(character.isalnum() or character == "-" for character in label)
    )


def setting(
    key: str, default: Any = None, cast: Callable[[str], Any] | None = None
) -> Any:
    """Read one configuration value from the environment at call time.

    Args:
        key: Environment variable name.
        default: Returned when the variable is unset or empty, and when the
            cast rejects the raw value.
        cast: Coercion applied to the raw string. When omitted it is inferred
            from ``type(default)``: ``bool`` uses
            :func:`~agent_connector_sdk.utilities.to_boolean`, ``int``/``float``
            use the builtin, ``list``/``dict`` parse JSON or comma lists, and
            anything else returns the raw string.
    """
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return default
    converter = cast or _inferred_cast(default)
    try:
        return converter(raw)
    except (TypeError, ValueError):
        return default


def _inferred_cast(default: Any) -> Callable[[str], Any]:
    for kind, caster in _CASTS:
        if isinstance(default, kind):
            return caster
    return str


def csv_values(raw: object) -> list[str]:
    """Split a comma-separated value into trimmed, non-empty parts."""
    return [part.strip() for part in str(raw or "").split(",") if part.strip()]


def config_file_path() -> Path:
    """Return the configuration document path this process would load.

    ``CONNECTOR_CONFIG_FILE`` wins; otherwise
    ``$XDG_CONFIG_HOME/agent-connector-sdk/config.json`` (``~/.config`` when
    ``XDG_CONFIG_HOME`` is unset).
    """
    explicit = setting(CONFIG_FILE_SETTING)
    if explicit:
        return Path(explicit).expanduser()
    base = setting("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "agent-connector-sdk" / "config.json"


def load_config(path: Path | None = None, *, reload: bool = False) -> Path | None:
    """Project the configuration document into ``os.environ``.

    Values are applied only for keys not already set in the environment. A
    missing document is not an error; an unreadable or invalid one is.

    Returns:
        The path that was loaded, or ``None`` when no document exists.

    Raises:
        ConfigurationError: the document is unreadable, is not a flat JSON
            object of scalars, or stores a credential value instead of a
            reference.
    """
    global _loaded_from
    target = path if path is not None else config_file_path()
    with _load_lock:
        if _loaded_from == target and not reload:
            return target
        if not target.is_file():
            return None
        for key, value in _read_document(target).items():
            os.environ.setdefault(key, value)
        _loaded_from = target
        return target


def _read_document(target: Path) -> dict[str, str]:
    try:
        payload = target.read_bytes()
    except OSError as exc:
        raise ConfigurationError("configuration document is unreadable") from exc
    if len(payload) > _MAX_CONFIG_BYTES:
        raise ConfigurationError("configuration document is too large")
    try:
        parsed = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("configuration document is not valid JSON") from exc
    if not isinstance(parsed, Mapping):
        raise ConfigurationError("configuration document must be a JSON object")
    return {
        str(key): _validated_value(str(key), value) for key, value in parsed.items()
    }


def _validated_value(key: str, value: object) -> str:
    if isinstance(value, bool):
        rendered = "true" if value else "false"
    elif isinstance(value, str | int | float):
        rendered = str(value)
    else:
        raise ConfigurationError(f"configuration key {key} must hold a scalar value")
    if len(rendered.encode("utf-8")) > _MAX_VALUE_BYTES or "\x00" in rendered:
        raise ConfigurationError(f"configuration key {key} holds an invalid value")
    if key.upper().endswith(_CREDENTIAL_SUFFIXES) and not rendered.startswith(
        _REFERENCE_SCHEMES
    ):
        raise ConfigurationError(
            f"configuration key {key} must hold an env:// or openbao:// secret "
            "reference, not a credential value"
        )
    return rendered
