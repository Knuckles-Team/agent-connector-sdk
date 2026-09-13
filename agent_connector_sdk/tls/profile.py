"""A resolved TLS profile and its adapters for HTTP and database clients."""

from __future__ import annotations

import ssl
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_connector_sdk.tls.errors import TransportSecurityError
from agent_connector_sdk.tls.material import MaterialStore

__all__ = ["ResolvedTLSProfile"]


@dataclass(frozen=True)
class ResolvedTLSProfile:
    """A path-safe summary plus client-specific adapters.

    ``repr`` shows only the name, source and trust flags; paths, proxy and key
    password stay out of logs.
    """

    name: str
    source: str
    configured: bool
    system_trust: bool
    trust_env: bool
    ssl_context: ssl.SSLContext = field(repr=False)
    minimum_version: ssl.TLSVersion = ssl.TLSVersion.TLSv1_2
    ca_bundle_path: Path | None = field(default=None, repr=False)
    ca_directory: Path | None = field(default=None, repr=False)
    client_cert_path: Path | None = field(default=None, repr=False)
    client_key_path: Path | None = field(default=None, repr=False)
    client_bundle_path: Path | None = field(default=None, repr=False)
    client_key_password: str | None = field(default=None, repr=False)
    proxy_url: str | None = field(default=None, repr=False)
    no_proxy: str | None = field(default=None, repr=False)
    materialized: tuple[Path, ...] = field(default=(), repr=False)

    @property
    def verify_enabled(self) -> bool:
        """Always ``True``: verification is an invariant of every profile."""
        return self.ssl_context.verify_mode == ssl.CERT_REQUIRED

    def httpx_kwargs(self) -> dict[str, Any]:
        """Arguments for ``httpx.Client``, ``AsyncClient`` and their transports."""
        kwargs: dict[str, Any] = {
            "verify": self.ssl_context,
            "trust_env": self.trust_env,
        }
        if self.proxy_url:
            kwargs["proxy"] = self.proxy_url
        return kwargs

    def requests_kwargs(self) -> dict[str, Any]:
        """Arguments for ``requests.request`` and ``Session.request``.

        Requests takes paths, not a context, and cannot use a key password: the
        client bundle holds the certificate with an unencrypted copy of the key
        in a private runtime file.
        """
        verify: bool | str = True
        if self.ca_bundle_path is not None or self.ca_directory is not None:
            verify = str(self.ca_bundle_path or self.ca_directory)
        kwargs: dict[str, Any] = {"verify": verify}
        if self.client_bundle_path is not None:
            kwargs["cert"] = str(self.client_bundle_path)
        if self.proxy_url:
            kwargs["proxies"] = {"http": self.proxy_url, "https": self.proxy_url}
        return kwargs

    def configure_requests_session(self, session: Any) -> Any:
        """Apply trust, client certificate and proxy settings to a Requests session."""
        kwargs = self.requests_kwargs()
        session.trust_env = self.trust_env
        session.verify = kwargs["verify"]
        if "cert" in kwargs:
            session.cert = kwargs["cert"]
        if "proxies" in kwargs:
            session.proxies.update(kwargs["proxies"])
        return session

    def psycopg_kwargs(self) -> dict[str, Any]:
        """Strict libpq parameters (``sslmode=verify-full``)."""
        if self.proxy_url or self.ca_directory is not None:
            raise TransportSecurityError("postgres_tls_profile_unsupported")
        kwargs: dict[str, Any] = {
            "sslmode": "verify-full",
            "ssl_min_protocol_version": self.minimum_version.name.replace("_", "."),
        }
        if self.ca_bundle_path is not None:
            kwargs["sslrootcert"] = str(self.ca_bundle_path)
        if self.client_cert_path is not None:
            kwargs["sslcert"] = str(self.client_cert_path)
            kwargs["sslkey"] = str(self.client_key_path)
        if self.client_key_password is not None:
            kwargs["sslpassword"] = self.client_key_password
        return kwargs

    def pymongo_kwargs(self) -> dict[str, Any]:
        """Strict PyMongo TLS parameters."""
        if self.proxy_url or self.ca_directory is not None:
            raise TransportSecurityError("mongodb_tls_profile_unsupported")
        kwargs: dict[str, Any] = {"tls": True}
        if self.ca_bundle_path is not None:
            kwargs["tlsCAFile"] = str(self.ca_bundle_path)
        if self.client_bundle_path is not None:
            kwargs["tlsCertificateKeyFile"] = str(self.client_bundle_path)
        return kwargs

    def cleanup(self) -> None:
        """Remove the runtime files this resolution wrote."""
        store = MaterialStore()
        store.created.extend(self.materialized)
        store.discard()
