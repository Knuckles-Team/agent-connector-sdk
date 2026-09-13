"""Resolve a service's TLS profile into a verified SSL context.

Profile document keys (every key optional):

``system_trust`` / ``trust_env``
    Booleans, default ``true``. Without system trust a CA must be configured.
``ca_bundle_ref`` | ``ca_bundle_pem`` | ``ca_bundle_path``; ``ca_directory``
    Additional trust anchors.
``client_cert_ref`` | ``client_cert_pem`` | ``client_cert_path`` and
``client_key_ref`` | ``client_key_pem`` | ``client_key_path``
    A client certificate; both halves or neither.
``client_key_password_ref`` | ``client_key_password``
    The key password.
``minimum_version``
    ``TLSv1.2`` (default) or ``TLSv1.3``.
``proxy_url_ref`` | ``proxy_url``; ``no_proxy``
    An ``http``, ``https``, ``socks5`` or ``socks5h`` proxy.

``verify`` and ``allow_insecure`` are rejected: there is no way to disable
verification.
"""

from __future__ import annotations

import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from agent_connector_sdk.credentials.references import SecretReferenceError
from agent_connector_sdk.credentials.resolution import resolve_secret_reference
from agent_connector_sdk.credentials.resolver import (
    CredentialResolver,
    CredentialUnavailableError,
)
from agent_connector_sdk.tls.context import (
    build_ssl_context,
    minimum_tls_version,
    unencrypted_key_pem,
)
from agent_connector_sdk.tls.errors import TransportSecurityError
from agent_connector_sdk.tls.material import MaterialStore, existing_path
from agent_connector_sdk.tls.profile import ResolvedTLSProfile
from agent_connector_sdk.tls.selection import SelectedProfile, select_profile

__all__ = ["resolve_tls_profile"]

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})
_PROXY_SCHEMES = frozenset({"http", "https", "socks5", "socks5h"})


class _Resolution:
    """Material resolution for one profile document."""

    def __init__(
        self,
        document: Mapping[str, Any],
        store: MaterialStore,
        resolver: CredentialResolver | None,
    ) -> None:
        self.document = document
        self.store = store
        self.resolver = resolver

    def secret(self, reference: object) -> str:
        try:
            return resolve_secret_reference(str(reference), self.resolver)
        except (SecretReferenceError, CredentialUnavailableError) as exc:
            raise TransportSecurityError("tls_secret_unavailable") from exc

    def pem_file(self, prefix: str, kind: str) -> Path | None:
        sources = {
            suffix: self.document.get(f"{prefix}_{suffix}")
            for suffix in ("ref", "pem", "path")
        }
        present = {
            key: value for key, value in sources.items() if value not in (None, "")
        }
        if len(present) > 1:
            raise TransportSecurityError("tls_material_source_ambiguous")
        if "ref" in present:
            return self.store.write(self.secret(present["ref"]), kind=kind)
        if "pem" in present:
            return self.store.write(str(present["pem"]), kind=kind)
        return existing_path(present["path"]) if "path" in present else None

    def optional_secret(self, key: str) -> str | None:
        reference, value = self.document.get(f"{key}_ref"), self.document.get(key)
        if reference and value:
            raise TransportSecurityError(f"{key}_source_ambiguous")
        if reference:
            return self.secret(reference)
        return str(value) if value else None


def _as_bool(value: object, *, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    rendered = str(value).strip().casefold()
    if rendered not in _TRUE | _FALSE:
        raise TransportSecurityError("tls_profile_boolean_invalid")
    return rendered in _TRUE


def _proxy(resolution: _Resolution) -> str | None:
    proxy = resolution.optional_secret("proxy_url")
    if proxy is None:
        return None
    parts = urlsplit(proxy)
    inline_credentials = bool(
        parts.username or parts.password
    ) and not resolution.document.get("proxy_url_ref")
    if (
        parts.scheme.casefold() not in _PROXY_SCHEMES
        or not parts.hostname
        or inline_credentials
    ):
        raise TransportSecurityError("tls_proxy_invalid")
    return proxy


@dataclass(frozen=True)
class _Trust:
    context: ssl.SSLContext
    ca_file: Path | None
    ca_directory: Path | None


@dataclass(frozen=True)
class _Identity:
    cert: Path | None = None
    key: Path | None = None
    bundle: Path | None = None
    password: str | None = None


def _trust(resolution: _Resolution, system_trust: bool) -> _Trust:
    document = resolution.document
    if {"verify", "allow_insecure"}.intersection(document):
        raise TransportSecurityError("tls_verification_control_rejected")
    ca_file = resolution.pem_file("ca_bundle", "ca")
    directory = document.get("ca_directory")
    ca_directory = existing_path(directory, directory=True) if directory else None
    if not system_trust and ca_file is None and ca_directory is None:
        raise TransportSecurityError("tls_trust_anchor_missing")
    context = build_ssl_context(
        system_trust=system_trust,
        ca_file=ca_file,
        ca_directory=ca_directory,
        minimum_version=minimum_tls_version(document.get("minimum_version")),
    )
    return _Trust(context, ca_file, ca_directory)


def _identity(resolution: _Resolution, context: ssl.SSLContext) -> _Identity:
    cert = resolution.pem_file("client_cert", "cert")
    key = resolution.pem_file("client_key", "key")
    password = resolution.optional_secret("client_key_password")
    if (cert is None) != (key is None):
        raise TransportSecurityError("tls_client_certificate_incomplete")
    if cert is None or key is None:
        return _Identity(password=password)
    context.load_cert_chain(certfile=str(cert), keyfile=str(key), password=password)
    payload = (
        cert.read_text(encoding="utf-8") + "\n" + unencrypted_key_pem(key, password)
    )
    bundle = resolution.store.write(payload, kind="bundle")
    return _Identity(cert, key, bundle, password)


def _build(selected: SelectedProfile, resolution: _Resolution) -> ResolvedTLSProfile:
    document = selected.document
    system_trust = _as_bool(document.get("system_trust"), default=True)
    trust = _trust(resolution, system_trust)
    identity = _identity(resolution, trust.context)
    return ResolvedTLSProfile(
        name=selected.name,
        source=selected.source,
        configured=selected.configured,
        system_trust=system_trust,
        trust_env=_as_bool(document.get("trust_env"), default=True),
        ssl_context=trust.context,
        minimum_version=trust.context.minimum_version,
        ca_bundle_path=trust.ca_file,
        ca_directory=trust.ca_directory,
        client_cert_path=identity.cert,
        client_key_path=identity.key,
        client_bundle_path=identity.bundle,
        client_key_password=identity.password,
        proxy_url=_proxy(resolution),
        no_proxy=str(document.get("no_proxy") or "").strip() or None,
        materialized=tuple(resolution.store.created),
    )


def resolve_tls_profile(
    service: str,
    *,
    profile_name: str | None = None,
    profile_ref: str | None = None,
    profile: Mapping[str, Any] | None = None,
    resolver: CredentialResolver | None = None,
    runtime_root: Path | None = None,
) -> ResolvedTLSProfile:
    """Resolve the TLS profile for ``service`` (see the module docstring).

    Args:
        service: Names the settings prefix, e.g. ``gitlab`` reads
            ``GITLAB_TLS_PROFILE`` and ``GITLAB_CA_BUNDLE_REF``.
        profile_name: A profile in the ``TLS_PROFILES_REF``/``TLS_PROFILES`` catalog.
        profile_ref: A secret reference holding a profile document or catalog.
        profile: An inline profile document; it may not hold credential values.
        resolver: Resolves secret references; the default resolver when omitted.
        runtime_root: Directory for materialized PEM files.

    Raises:
        TransportSecurityError: the profile is invalid or its material is
            unavailable. Files already written for this call are removed.
    """
    store = MaterialStore(runtime_root)
    resolution = _Resolution({}, store, resolver)
    selected = select_profile(
        service,
        profile_name=profile_name,
        profile_ref=profile_ref,
        profile=profile,
        resolve=resolution.secret,
    )
    resolution.document = selected.document
    try:
        return _build(selected, resolution)
    except TransportSecurityError:
        store.discard()
        raise
    except (OSError, ssl.SSLError, ValueError, TypeError) as exc:
        store.discard()
        raise TransportSecurityError(
            f"tls_profile_material_invalid ({type(exc).__name__})"
        ) from None
