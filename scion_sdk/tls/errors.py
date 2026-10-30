"""The TLS profile failure type."""

from __future__ import annotations

__all__ = ["TransportSecurityError"]


class TransportSecurityError(RuntimeError):
    """A TLS profile is invalid or its material is unavailable.

    Messages are stable codes such as ``tls_trust_anchor_missing``; they never
    contain paths, hosts, secret references or secret values.
    """
