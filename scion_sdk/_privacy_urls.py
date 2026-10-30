"""Host and URL checks behind :func:`scion_sdk.privacy.public_http_url`."""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import SplitResult, urlsplit

_NON_PUBLIC_SUFFIXES = (".local", ".localhost", ".internal", ".arpa", ".lan", ".home")


def _public_hostname(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return (
            "." in host
            and host not in {"localhost"}
            and not host.endswith(_NON_PUBLIC_SUFFIXES)
        )
    return address.is_global


def _split_http_url(value: Any) -> SplitResult | None:
    if not isinstance(value, str) or any(c in value for c in "\r\n\t "):
        return None
    try:
        return urlsplit(value)
    except ValueError:
        return None
