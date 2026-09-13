"""Small value coercion and logging helpers shared by fleet connectors.

Extracted from ``agent_utilities.base_utilities`` (``to_boolean``, ``to_integer``,
``to_float``, ``get_logger``) with two deliberate changes:

* coercers never expand ``$VAR`` references inside the value they are handed;
  environment access is the job of :func:`agent_connector_sdk.config.setting`;
* list/dict coercion accepts JSON documents and comma-separated lists only, and
  raises :class:`ValueError` for anything else instead of guessing.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

__all__ = [
    "get_logger",
    "to_boolean",
    "to_dict",
    "to_float",
    "to_integer",
    "to_list",
]

_TRUE_TOKENS = frozenset({"t", "true", "y", "yes", "1", "on"})


def to_boolean(value: object = None) -> bool:
    """Return ``True`` for a boolean true or a recognised true token.

    Recognised tokens (case-insensitive, surrounding whitespace ignored) are
    ``t``, ``true``, ``y``, ``yes``, ``1`` and ``on``. Everything else, including
    ``None`` and the empty string, is ``False``.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in _TRUE_TOKENS


def to_integer(value: object = None) -> int:
    """Return ``value`` as an ``int``, or ``0`` when it is empty or not integral."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if value is None:
        return 0
    try:
        return int(str(value).strip())
    except ValueError:
        return 0


def to_float(value: object = None) -> float:
    """Return ``value`` as a ``float``, or ``0.0`` when it is empty or not numeric."""
    if isinstance(value, float):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    if value is None:
        return 0.0
    try:
        return float(str(value).strip())
    except ValueError:
        return 0.0


def to_list(value: object = None) -> list[Any]:
    """Return a list from a list, a JSON array, or a comma-separated string.

    Raises:
        ValueError: when ``value`` is a JSON document that is not an array, or a
            type that has no list reading.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if not isinstance(value, str):
        raise ValueError("value has no list form")
    text = value.strip()
    if not text:
        return []
    if text.startswith("["):
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError("value is not a JSON array")
        return parsed
    return [part.strip() for part in text.split(",") if part.strip()]


def to_dict(value: object = None) -> dict[str, Any]:
    """Return a dict from a dict or a JSON object document.

    Raises:
        ValueError: when ``value`` is not a mapping or a JSON object.
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str):
        raise ValueError("value has no mapping form")
    text = value.strip()
    if not text:
        return {}
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("value is not a JSON object")
    return parsed


def get_logger(name: str) -> logging.Logger:
    """Return a logger that writes to stderr at INFO level.

    Stdout is reserved for the MCP stdio JSON-RPC stream, so the handler this
    installs always targets stderr. A logger that already has handlers is
    returned unchanged.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(handler)
    return logger
