"""Per-domain pacing and robots.txt policy for web-source connectors."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
import urllib.robotparser
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from scion_sdk.ports._web_refusal import WebSourceRefused

_logger = logging.getLogger("scion_sdk.ports.web_source")

#: The default per-domain spacing: one request per second.
DEFAULT_MIN_INTERVAL_S = 1.0


def _origin_of(url: str) -> str:
    parts = httpx.URL(url)
    host = parts.raw_host.decode("ascii").rstrip(".")
    if parts.scheme not in {"http", "https"} or not host:
        raise ValueError("absolute URL required")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        authority = host.lower()
    else:
        authority = f"[{address}]" if address.version == 6 else str(address)
    port = f":{parts.port}" if parts.port is not None else ""
    return f"{parts.scheme}://{authority}{port}"


def _origin(url: str) -> str:
    try:
        return _origin_of(url)
    except (httpx.InvalidURL, UnicodeError, ValueError) as exc:
        raise WebSourceRefused("policy_refused", "invalid web URL") from exc


def _domain_of(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname
    _ = parts.port
    if parts.scheme not in {"http", "https"} or not host:
        raise ValueError("absolute URL required")
    host = httpx.URL(url).raw_host.decode("ascii").rstrip(".")
    if not host or any(char.isspace() for char in host):
        raise ValueError("invalid host")
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return host.lower()


def _rate_limit_domain(url: str) -> str:
    try:
        return _domain_of(url)
    except (httpx.InvalidURL, UnicodeError, ValueError) as exc:
        raise WebSourceRefused("policy_refused", "invalid web URL") from exc


@dataclass
class DomainRateLimiter:
    """Space requests to one host at least ``min_interval_s`` apart."""

    min_interval_s: float = DEFAULT_MIN_INTERVAL_S
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    _next: dict[str, float] = field(default_factory=dict)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    async def acquire(self, url: str) -> None:
        domain = _rate_limit_domain(url)
        lock = self._locks.setdefault(domain, asyncio.Lock())
        async with lock:
            now = self.clock()
            wait = self._next.get(domain, now) - now
            if wait > 0:
                await self.sleep(wait)
                now = self.clock()
            self._next[domain] = now + self.min_interval_s


RobotsLoader = Callable[[str], Awaitable[tuple[int, str]]]


@dataclass
class RobotsRules:
    """``robots.txt`` per origin, cached for ``ttl_s`` (one hour by default).

    ``loader`` reads one ``robots.txt`` URL and returns ``(status, body)``; the
    connector supplies it, so the SDK makes no request itself. A 4xx file allows
    everything (RFC 9309 section 2.3.1.3); a 5xx or failed read disallows
    everything until the entry expires.
    """

    loader: RobotsLoader
    user_agent: str
    ttl_s: float = 3600.0
    clock: Callable[[], float] = time.monotonic
    _rules: dict[str, tuple[float, urllib.robotparser.RobotFileParser]] = field(
        default_factory=dict
    )
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    async def check(self, url: str) -> None:
        """Raise ``robots_disallowed`` unless ``url`` may be fetched."""
        if not await self.allowed(url):
            raise WebSourceRefused(
                "robots_disallowed", "robots policy disallows the page"
            )

    async def allowed(self, url: str) -> bool:
        origin = _origin(url)
        cached = self._rules.get(origin)
        if cached is None or cached[0] < self.clock():
            lock = self._locks.setdefault(origin, asyncio.Lock())
            async with lock:
                cached = self._rules.get(origin)
                if cached is None or cached[0] < self.clock():
                    parser = await self._load(origin)
                    cached = (self.clock() + self.ttl_s, parser)
                    self._rules[origin] = cached
        return cached[1].can_fetch(self.user_agent, url)

    async def _load(self, origin: str) -> urllib.robotparser.RobotFileParser:
        parser = urllib.robotparser.RobotFileParser()
        try:
            status, body = await self.loader(f"{origin}/robots.txt")
        except WebSourceRefused as refused:
            if refused.reason in {"egress_denied", "policy_refused"}:
                raise
            status, body = 503, ""
        except Exception as exc:
            # RFC 9309: an unreachable robots.txt disallows the whole origin.
            _logger.info(
                "robots.txt for %s is unreadable: %s", origin, type(exc).__name__
            )
            status, body = 503, ""
        if status >= 500:
            # RobotFileParser's documented switches are not in its type stubs.
            vars(parser).update(disallow_all=True)
        elif status >= 400:
            vars(parser).update(allow_all=True)
        else:
            parser.parse(body.splitlines())
        return parser
