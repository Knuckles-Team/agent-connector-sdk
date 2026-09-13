"""Resolve ``openbao://`` references against an OpenBao KV v2 mount."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from urllib.parse import quote, urlsplit

import httpx

from agent_connector_sdk.config import setting
from agent_connector_sdk.credentials.references import (
    SecretReference,
    SecretReferenceError,
    parse_secret_reference,
)
from agent_connector_sdk.credentials.resolver import (
    CredentialUnavailableError,
    EnvironmentCredentialResolver,
)

__all__ = ["OpenBaoCredentialResolver"]


def _is_loopback_host(host: str) -> bool:
    if host in {"localhost", "localhost."}:
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def _validated_address(address: str) -> str:
    parts = urlsplit(address)
    host = parts.hostname or ""
    malformed = (
        parts.scheme not in {"http", "https"}
        or not host
        or bool(parts.username or parts.password or parts.query or parts.fragment)
    )
    if malformed:
        raise ValueError("OpenBao address is invalid")
    if parts.scheme == "http" and not _is_loopback_host(host):
        raise ValueError("OpenBao address requires HTTPS outside loopback")
    return address.rstrip("/")


def _kv2_field(document: object, field: str) -> str | None:
    envelope = document.get("data") if isinstance(document, Mapping) else None
    data = envelope.get("data") if isinstance(envelope, Mapping) else None
    value = data.get(field) if isinstance(data, Mapping) else None
    return value if isinstance(value, str) and value else None


class OpenBaoCredentialResolver:
    """Reads secret fields from OpenBao.

    Args:
        address: OpenBao base URL; HTTPS is required outside loopback.
        token: The token used for reads (see :meth:`from_settings`).
        namespace: Optional OpenBao namespace header.
        http_client: Client used for requests; injected by tests and by a
            composition root that manages connection pooling.
    """

    def __init__(
        self,
        address: str,
        token: str,
        *,
        namespace: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not token:
            raise ValueError("OpenBao token is required")
        self._base = _validated_address(address)
        self._headers = {"X-Vault-Token": token}
        if namespace:
            self._headers["X-Vault-Namespace"] = namespace
        self._client = http_client or httpx.Client(timeout=10.0)

    @classmethod
    def from_settings(
        cls, *, http_client: httpx.Client | None = None
    ) -> OpenBaoCredentialResolver | None:
        """Build from ``OPENBAO_ADDR`` and ``OPENBAO_TOKEN_REF`` (``env://`` only).

        The token that unlocks OpenBao cannot itself live in OpenBao. Returns
        ``None`` when ``OPENBAO_ADDR`` is unset.
        """
        address = setting("OPENBAO_ADDR")
        if not address:
            return None
        token_reference = parse_secret_reference(str(setting("OPENBAO_TOKEN_REF", "")))
        if token_reference.scheme != "env":
            raise SecretReferenceError("OPENBAO_TOKEN_REF must be an env:// reference")
        return cls(
            str(address),
            EnvironmentCredentialResolver().resolve(token_reference),
            namespace=setting("OPENBAO_NAMESPACE"),
            http_client=http_client,
        )

    def resolve(self, reference: SecretReference) -> str:
        """Read the referenced field."""
        if reference.scheme != "openbao":
            raise CredentialUnavailableError("reference scheme is not openbao")
        url = (
            f"{self._base}/v1/{quote(reference.mount, safe='')}/data/"
            f"{quote(reference.path, safe='/')}"
        )
        params = {"version": str(reference.version)} if reference.version else None
        try:
            response = self._client.get(url, headers=self._headers, params=params)
            document = response.raise_for_status().json()
        except (httpx.HTTPError, ValueError) as exc:
            raise CredentialUnavailableError("secret reference is unavailable") from exc
        value = _kv2_field(document, reference.field)
        if value is None:
            raise CredentialUnavailableError("secret reference is unavailable")
        return value
