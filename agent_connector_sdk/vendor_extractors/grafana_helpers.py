"""Low-level field access helpers for the Grafana extractor (see ``grafana.py``)."""

from __future__ import annotations

import re
from typing import Any


def get(record: Any, key: str, default: Any = None) -> Any:
    """Tolerant field access for dict records (or attr-style objects)."""
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def call(client: Any, name: str) -> list[Any]:
    """Call a client method if present, returning a list (tolerant)."""
    method = getattr(client, name, None)
    if not callable(method):
        return []
    result = method()
    return list(result) if result else []


def scalar(value: Any) -> str | None:
    """Normalise a value to a non-empty scalar string, else ``None``."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def service_from_labels(labels: Any) -> str | None:
    """Pull a service name from a labels mapping (service/app/job keys)."""
    if not isinstance(labels, dict):
        return None
    for key in ("service", "app", "job", "service_name"):
        name = scalar(labels.get(key))
        if name:
            return name
    return None


def service_from_title(title: Any) -> str | None:
    """Heuristically pull a service token from an explicit title marker."""
    text = scalar(title)
    if not text:
        return None
    match = re.search(r"service\s*[:=]\s*([A-Za-z0-9._-]+)", text, re.IGNORECASE)
    return match.group(1) if match else None
