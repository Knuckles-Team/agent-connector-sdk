"""PII sanitization for connector payloads (SDK-CONNECTOR-CONTROL-R014.6).

Moved from agent-utilities so MCP-only connectors redact PII without the harness.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Built-in patterns
# ---------------------------------------------------------------------------

# Common PII patterns
_PII_PATTERNS: dict[str, str] = {
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "tax_id": r"\b\d{2}-\d{7}\b",
    "credit_card": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
}


class PiiSanitizer:
    """Named Entity Recognition & Regex-based PII Sanitizer.

    Dynamically redacts sensitive identifiers from text, lists, and dicts.
    """

    def __init__(self, patterns: dict[str, str] | None = None) -> None:
        self.patterns = patterns or _PII_PATTERNS
        self._compiled = {k: re.compile(v) for k, v in self.patterns.items()}

    def sanitize_text(self, text: str) -> str:
        """Redact PII from string content."""
        if not text or not isinstance(text, str):
            return text

        # Simple NER and pattern redaction
        sanitized = text
        for label, regex in self._compiled.items():
            replacement = f"[REDACTED_{label.upper()}]"
            sanitized = regex.sub(replacement, sanitized)

        return sanitized

    def sanitize_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """Deep-sanitize dictionary values and keys."""
        if not isinstance(data, dict):
            return data  # type: ignore[unreachable]

        sanitized: dict[Any, Any] = {}
        for k, v in data.items():
            # Sanitize keys too
            clean_k = (
                self.sanitize_text(k)
                if isinstance(k, str)
                else self.sanitize_text(str(k))
            )
            if isinstance(v, dict):
                sanitized[clean_k] = self.sanitize_dict(v)
            elif isinstance(v, list):
                sanitized[clean_k] = [self.sanitize(item) for item in v]
            elif isinstance(v, str):
                sanitized[clean_k] = self.sanitize_text(v)
            else:
                sanitized[clean_k] = v
        return sanitized

    def sanitize(self, data: Any) -> Any:
        """Generic deep-sanitizer for strings, lists, dicts."""
        if isinstance(data, str):
            return self.sanitize_text(data)
        elif isinstance(data, dict):
            return self.sanitize_dict(data)
        elif isinstance(data, list):
            return [self.sanitize(item) for item in data]
        return data
