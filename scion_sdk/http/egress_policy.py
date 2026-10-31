"""The egress allow-list policy and private-host normalisation."""

from __future__ import annotations

import ipaddress
from collections.abc import Collection
from dataclasses import dataclass

import httpx


class EgressPolicyError(ValueError):
    """``host`` is not a permitted egress destination under this policy."""


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def _is_private(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private and not address.is_loopback


@dataclass(frozen=True)
class EgressOptions:
    """The knobs of the egress policy; the defaults enforce it strictly.

    Attributes:
        pin_egress: When ``False``, the policy is not enforced at all (an
            explicit, named escape hatch; the default enforces it).
        allowed_private_hosts: Private-network hosts this policy allows,
            compared after hostname case and trailing-dot normalization.
        allow_loopback: Permit a loopback destination (``127.0.0.1``,
            ``::1``, ``localhost``).
    """

    pin_egress: bool = True
    allowed_private_hosts: Collection[str] = ()
    allow_loopback: bool = False


_STRICT_EGRESS = EgressOptions()


def check_egress_destination(
    host: str, options: EgressOptions = _STRICT_EGRESS
) -> None:
    """Reject ``host`` unless the policy explicitly allows it.

    Args:
        host: The outbound request's destination hostname or address.
        options: The :class:`EgressOptions` policy; strict by default.

    Raises:
        EgressPolicyError: ``host`` is loopback or a private-network address
            and not named by ``allowed_private_hosts`` or ``allow_loopback``.
    """
    if not options.pin_egress:
        return
    host = host.lower().rstrip(".")
    allow_loopback = options.allow_loopback
    allowed_private_hosts = normalize_private_hosts(options.allowed_private_hosts)
    if _is_loopback(host):
        if not allow_loopback and host not in allowed_private_hosts:
            raise EgressPolicyError(f"loopback destination is not permitted: {host}")
        return
    if _is_private(host) and host not in allowed_private_hosts:
        raise EgressPolicyError(f"private-network destination is not permitted: {host}")


class PinnedEgressViolation(httpx.TransportError):
    """An outbound request failed the DNS-pinning or peer-identity boundary."""


def _label_is_valid(label: str) -> bool:
    return (
        bool(label)
        and len(label) <= 63
        and not label.startswith("-")
        and not label.endswith("-")
        and all(c.isalnum() or c == "-" for c in label)
    )


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _normalize_private_host(raw: object) -> str:
    host = str(raw).strip().lower().rstrip(".")
    if not host.isascii():
        raise ValueError("private egress hosts must be ASCII")
    if not _is_exact_hostname(host):
        raise ValueError("private egress hosts must be exact hostnames")
    return host


def _is_exact_hostname(host: str) -> bool:
    if (
        not host
        or len(host) > 253
        or any(ord(c) < 33 for c in host)
        or any(c in host for c in "/@*?#[]")
    ):
        return False
    return _is_ip_literal(host) or all(
        _label_is_valid(label) for label in host.split(".")
    )


def normalize_private_hosts(hosts: Collection[str]) -> frozenset[str]:
    """Validate the explicit private-host allow-list into exact lowercase names.

    Raises:
        ValueError: a host is not an exact ASCII hostname or IP literal (no
            wildcards, paths, credentials or brackets), or there are over 256.
    """
    normalized = {_normalize_private_host(raw) for raw in hosts}
    if len(normalized) > 256:
        raise ValueError("private egress host allowlist is too large")
    return frozenset(normalized)
