"""Fail closed for MCP listeners exposed beyond loopback.

Extracted from the network exposure validation in
``agent_utilities.mcp.server_factory``: a non-loopback network listener needs
authentication, a TLS boundary (direct TLS or a trusted terminating ingress)
and an exact host allowlist. Host names other than ``localhost`` are treated as
remote; DNS is not consulted because a name can be rebound after validation.
"""

from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path

from agent_connector_sdk.config import csv_values

__all__ = ["NetworkExposureError", "is_loopback_host", "validate_network_exposure"]

_NETWORK_TRANSPORTS = frozenset({"streamable-http", "sse"})


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


def _direct_tls(args: argparse.Namespace) -> bool:
    """Whether direct TLS material is configured; a half or missing pair raises."""
    certfile, keyfile = str(args.tls_certfile or ""), str(args.tls_keyfile or "")
    if bool(certfile) != bool(keyfile):
        raise NetworkExposureError("TLS needs both certificate and key")
    if certfile and not (Path(certfile).is_file() and Path(keyfile).is_file()):
        raise NetworkExposureError("TLS certificate or key is unavailable")
    return bool(certfile)


def _require_tls_boundary(args: argparse.Namespace) -> None:
    certfile = _direct_tls(args)
    if args.tls_terminated and not args.trusted_proxy_cidrs:
        raise NetworkExposureError(
            "a TLS-terminating ingress needs trusted proxy CIDRs"
        )
    if not certfile and not args.tls_terminated:
        raise NetworkExposureError("an exposed MCP listener requires TLS")


def validate_network_exposure(args: argparse.Namespace) -> None:
    """Refuse a non-loopback network listener without auth, TLS and allowed hosts.

    Raises:
        NetworkExposureError: naming the missing boundary.
    """
    if args.transport not in _NETWORK_TRANSPORTS or is_loopback_host(args.host):
        return
    if args.auth_type == "none":
        raise NetworkExposureError("an exposed MCP listener requires authentication")
    _require_tls_boundary(args)
    hosts = csv_values(args.allowed_hosts)
    if not hosts or any("*" in host for host in hosts):
        raise NetworkExposureError(
            "an exposed MCP listener requires exact allowed hosts"
        )
