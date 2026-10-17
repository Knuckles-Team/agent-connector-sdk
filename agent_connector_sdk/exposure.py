"""Network exposure error and address classification primitives."""

from __future__ import annotations

import ipaddress

__all__ = ["NetworkExposureError", "is_loopback_host"]


class NetworkExposureError(RuntimeError):
    """A non-loopback listener lacks authentication, TLS or a host allowlist."""


def is_loopback_host(host: object) -> bool:
    """True only for ``localhost`` or a loopback IP literal."""
    value = str(host or "").strip().lower()
    if value in {"localhost", "localhost."}:
        return True
    try:
        return ipaddress.ip_address(value.strip("[]").split("%", 1)[0]).is_loopback
    except ValueError:
        return False
