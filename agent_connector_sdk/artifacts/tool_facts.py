"""Public estimates for canonical captured tool bodies.

The estimate is not a tokenizer count and does not publish pack annotations.
Callers may replace it with a measured tokenizer count where available.
"""

from __future__ import annotations

__all__ = ["DEFAULT_SCHEMA_BYTES_PER_TOKEN", "schema_tokens"]

DEFAULT_SCHEMA_BYTES_PER_TOKEN = 4


def schema_tokens(body: str) -> int:
    """Estimate tokens from the UTF-8 bytes of a canonical tool body."""
    byte_count = len(body.encode("utf-8"))
    return (
        byte_count + DEFAULT_SCHEMA_BYTES_PER_TOKEN - 1
    ) // DEFAULT_SCHEMA_BYTES_PER_TOKEN
