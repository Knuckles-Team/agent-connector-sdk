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

import json
import os
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from agent_connector_sdk.utilities import to_boolean, to_dict, to_list

__all__ = [
    "CONFIG_FILE_SETTING",
    "ConfigurationError",
    "config_file_path",
    "csv_values",
    "load_config",
    "setting",
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
