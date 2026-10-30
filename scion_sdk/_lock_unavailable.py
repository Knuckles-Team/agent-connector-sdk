"""The lock-contention error shared by the file-lock platform branches."""

from __future__ import annotations


class LockUnavailable(OSError):
    """Raised when a non-blocking lock acquire fails because a peer holds it."""
