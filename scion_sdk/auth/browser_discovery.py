"""OIDC discovery for the browser OAuth manager."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("scion_sdk.auth.browser")


class _OidcDiscovery:
    """Resolve authorization and token endpoints, falling back to configured ones."""

    auth_endpoint: str
    token_endpoint: str
    oidc_discovery_url: str | None
    validate_endpoint_fn: Callable[[str, str], str] | None

    def _discover_endpoints(self) -> tuple[str, str]:
        """Perform OIDC Discovery to dynamically resolve auth and token endpoints if URL is configured."""
        if not self.oidc_discovery_url:
            return self.auth_endpoint, self.token_endpoint

        try:
            return self._validated_endpoints(self._fetch_discovery())
        except Exception as exc:
            logger.error(
                "OIDC discovery failed for %s: %s", self.oidc_discovery_url, exc
            )
            # Graceful fallback to initial values
            return self.auth_endpoint, self.token_endpoint

    def _fetch_discovery(self) -> dict[str, Any]:
        import httpx

        response = httpx.get(
            self.oidc_discovery_url or "",
            headers={"Accept": "application/json"},
            timeout=15.0,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        return payload

    def _validated_endpoints(self, payload: dict[str, Any]) -> tuple[str, str]:
        auth_ep = payload.get("authorization_endpoint", self.auth_endpoint)
        token_ep = payload.get("token_endpoint", self.token_endpoint)
        if self.validate_endpoint_fn:
            auth_ep = self.validate_endpoint_fn(auth_ep, "authorization_endpoint")
            token_ep = self.validate_endpoint_fn(token_ep, "token_endpoint")
        return auth_ep, token_ep
