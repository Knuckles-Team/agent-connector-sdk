"""Privacy guard for values that cross a persistence or telemetry boundary.

Replaces ``agent_utilities.security.persistence_privacy``. Deterministic and
dependency-free: it removes known identifier formats (SSN, card, e-mail, token,
phone, IP and MAC addresses, IBAN, machine paths), secret-bearing fields,
location fields and personal-name fields before a value enters the knowledge
graph, logs or an external trace sink. Structural identifiers (``id``,
``source``, ``target`` ...) keep their value so keys and edges never collapse.

Runtime deny terms are the local account and host names plus the optional list
behind ``PERSISTENCE_PRIVACY_DENY_TERMS_REF`` (a secret reference); the terms
never appear in reports. ``persistence_reference`` keys its digest with the
secret behind ``PERSISTENCE_IDENTITY_HMAC_KEY_REF`` when set.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from agent_connector_sdk.privacy_reference import persistence_reference
from agent_connector_sdk.privacy_rules import (
    PATTERNS,
    STRUCTURAL_ID_FIELDS,
    field_name,
    field_redaction,
    runtime_deny_terms,
    usable_terms,
)

__all__ = [
    "PersistencePrivacyGuard",
    "PrivacyReport",
    "persistence_reference",
    "sanitize_for_persistence",
]


@dataclass(frozen=True)
class PrivacyReport:
    """Non-sensitive summary of one sanitization pass."""

    redactions: int
    detected_types: tuple[str, ...]

    @property
    def changed(self) -> bool:
        """Whether anything was redacted."""
        return self.redactions > 0

    def as_dict(self) -> dict[str, Any]:
        """The report as JSON data."""
        return {
            "redactions": self.redactions,
            "detected_types": list(self.detected_types),
        }


class PersistencePrivacyGuard:
    """Deep sanitizer for data entering durable or external observability stores."""

    def __init__(self, *, deny_terms: Iterable[str] | None = None) -> None:
        terms = runtime_deny_terms() if deny_terms is None else usable_terms(deny_terms)
        self._patterns = (
            *PATTERNS,
            *(
                ("identity_term", re.compile(re.escape(term), re.IGNORECASE))
                for term in terms
            ),
        )

    def sanitize(self, value: Any) -> tuple[Any, PrivacyReport]:
        """A sanitized copy of ``value`` and what was redacted."""
        counts: dict[str, int] = {}
        clean = self._value(value, counts, ())
        return clean, PrivacyReport(sum(counts.values()), tuple(sorted(counts)))

    def sanitize_text(self, value: str) -> tuple[str, PrivacyReport]:
        """:meth:`sanitize` for one string."""
        clean, report = self.sanitize(value)
        return str(clean), report

    def _value(
        self, value: Any, counts: dict[str, int], context: tuple[str, ...]
    ) -> Any:
        if isinstance(value, str):
            return self._text(value, counts)
        if isinstance(value, dict):
            return {
                key: self._entry(str(key), item, counts, context)
                for key, item in value.items()
            }
        if isinstance(value, list | tuple | set | frozenset):
            return [self._value(item, counts, context) for item in value]
        if isinstance(value, int | float | bool) or value is None:
            return value
        counts["opaque_object"] = counts.get("opaque_object", 0) + 1
        return f"[REDACTED_OBJECT:{type(value).__name__}]"

    def _entry(
        self, key: str, item: Any, counts: dict[str, int], context: tuple[str, ...]
    ) -> Any:
        field = field_name(key)
        redaction = field_redaction(field, item, context)
        if redaction is not None:
            label, replacement = redaction
            counts[label] = counts.get(label, 0) + 1
            return replacement
        if field in STRUCTURAL_ID_FIELDS and isinstance(item, str):
            return item
        return self._value(item, counts, (*context, field))

    def _text(self, value: str, counts: dict[str, int]) -> str:
        clean = value
        for label, pattern in self._patterns:
            clean, count = pattern.subn(f"[REDACTED_{label.upper()}]", clean)
            if count:
                counts[label] = counts.get(label, 0) + count
        return clean


def sanitize_for_persistence(
    value: Any, *, deny_terms: Iterable[str] | None = None
) -> tuple[Any, PrivacyReport]:
    """Sanitize ``value``; the report carries only counts and types."""
    return PersistencePrivacyGuard(deny_terms=deny_terms).sanitize(value)
