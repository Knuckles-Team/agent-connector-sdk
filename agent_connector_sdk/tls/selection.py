"""Select the TLS profile document for one service.

Resolution order: an explicit ``profile`` mapping; a profile reference (explicit,
``<SERVICE>_TLS_PROFILE_REF`` or ``TLS_PROFILE_REF``); a profile name (explicit,
``<SERVICE>_TLS_PROFILE`` or ``TLS_PROFILE``) looked up in the catalog at
``TLS_PROFILES_REF`` or ``TLS_PROFILES``; then per-service and global
environment settings. An explicit selector is an isolated decision: the missing
half is never filled from the environment.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from agent_connector_sdk.config import setting
from agent_connector_sdk.tls.errors import TransportSecurityError

__all__ = ["SelectedProfile", "select_profile", "service_prefix"]

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_MAX_PROFILE_BYTES = 256_000
#: Credential values: allowed only in a document read from a secret reference.
_CREDENTIAL_KEYS = frozenset({"client_key_pem", "client_key_password"})
#: Profile key -> (per-service suffix, global setting).
_ENVIRONMENT_KEYS: dict[str, tuple[str, str]] = {
    "ca_bundle_ref": ("CA_BUNDLE_REF", "TLS_CA_BUNDLE_REF"),
    "ca_bundle_path": ("CA_BUNDLE", "TLS_CA_BUNDLE"),
    "ca_directory": ("CA_DIRECTORY", "TLS_CA_DIRECTORY"),
    "client_cert_ref": ("CLIENT_CERT_REF", "TLS_CLIENT_CERT_REF"),
    "client_cert_path": ("CLIENT_CERT", "TLS_CLIENT_CERT"),
    "client_key_ref": ("CLIENT_KEY_REF", "TLS_CLIENT_KEY_REF"),
    "client_key_path": ("CLIENT_KEY", "TLS_CLIENT_KEY"),
    "client_key_password_ref": (
        "CLIENT_KEY_PASSWORD_REF",
        "TLS_CLIENT_KEY_PASSWORD_REF",
    ),
    "proxy_url_ref": ("PROXY_URL_REF", "TLS_PROXY_URL_REF"),
    "proxy_url": ("PROXY_URL", "TLS_PROXY_URL"),
    "no_proxy": ("NO_PROXY", "NO_PROXY"),
    "minimum_version": ("TLS_MINIMUM_VERSION", "TLS_MINIMUM_VERSION"),
    "system_trust": ("TLS_SYSTEM_TRUST", "TLS_SYSTEM_TRUST"),
    "trust_env": ("TLS_TRUST_ENV", "TLS_TRUST_ENV"),
}


@dataclass(frozen=True)
class SelectedProfile:
    """The chosen profile document and where it came from."""

    name: str
    source: str
    configured: bool
    document: dict[str, Any]


def service_prefix(service: str) -> str:
    """The setting prefix for ``service``: upper-case, non-alphanumerics as ``_``."""
    normalized = "".join(
        character if character.isalnum() else "_"
        for character in str(service or "").strip().upper()
    ).strip("_")
    if not normalized:
        raise TransportSecurityError("tls_service_invalid")
    return normalized


def _first_setting(*keys: str) -> str:
    for key in keys:
        value = str(setting(key, "") or "").strip()
        if value:
            return value
    return ""


def _parse_document(raw: str) -> dict[str, Any]:
    if len(raw.encode("utf-8")) > _MAX_PROFILE_BYTES:
        raise TransportSecurityError("tls_profile_too_large")
    try:
        value = json.loads(raw)
    except ValueError:
        raise TransportSecurityError("tls_profile_invalid") from None
    if not isinstance(value, dict):
        raise TransportSecurityError("tls_profile_invalid")
    return value


def _named(catalog: Mapping[str, Any], name: str) -> dict[str, Any]:
    if _NAME_RE.fullmatch(name) is None:
        raise TransportSecurityError("tls_profile_name_invalid")
    profiles = catalog.get("profiles", catalog)
    selected = profiles.get(name) if isinstance(profiles, Mapping) else None
    if not isinstance(selected, Mapping):
        raise TransportSecurityError("tls_profile_not_found")
    return dict(selected)


def _from_environment(prefix: str) -> SelectedProfile:
    document: dict[str, Any] = {}
    for key, (suffix, global_key) in _ENVIRONMENT_KEYS.items():
        value = _first_setting(f"{prefix}_{suffix}", global_key)
        if value:
            document[key] = value
    configured = bool(document)
    if not any(
        key in document for key in ("ca_bundle_ref", "ca_bundle_path", "ca_directory")
    ):
        standard_file = _first_setting("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")
        standard_dir = _first_setting("SSL_CERT_DIR")
        if standard_file or standard_dir:
            document["ca_bundle_path" if standard_file else "ca_directory"] = (
                standard_file or standard_dir
            )
    return SelectedProfile("default", "environment", configured, document)


def _selectors(prefix: str, name: str | None, ref: str | None) -> tuple[str, str]:
    if name or ref:
        return str(name or "").strip(), str(ref or "").strip()
    return (
        _first_setting(f"{prefix}_TLS_PROFILE", "TLS_PROFILE"),
        _first_setting(f"{prefix}_TLS_PROFILE_REF", "TLS_PROFILE_REF"),
    )


def select_profile(
    service: str,
    *,
    profile_name: str | None,
    profile_ref: str | None,
    profile: Mapping[str, Any] | None,
    resolve: Callable[[str], str],
) -> SelectedProfile:
    """Choose the profile document.

    ``resolve`` turns a secret reference into its value. Credential values
    (``client_key_pem``, ``client_key_password``) are accepted only in a
    document read from a secret reference.

    Raises:
        TransportSecurityError: the selection is invalid or unavailable.
    """
    prefix = service_prefix(service)
    name, ref = _selectors(prefix, profile_name, profile_ref)
    if profile is not None:
        selected = SelectedProfile(name or "inline", "inline", True, dict(profile))
    elif ref:
        document = _parse_document(resolve(ref))
        chosen = _named(document, name) if name else document
        return SelectedProfile(name or "default", "secret_ref", True, chosen)
    elif name:
        selected = _from_catalog(name, resolve)
    else:
        selected = _from_environment(prefix)
    secret_backed = selected.source in _SECRET_BACKED_SOURCES
    if not secret_backed and _CREDENTIAL_KEYS.intersection(selected.document):
        raise TransportSecurityError("tls_credential_value_in_configuration")
    return selected


_SECRET_BACKED_SOURCES = frozenset({"secret_ref", "secret_catalog"})


def _from_catalog(name: str, resolve: Callable[[str], str]) -> SelectedProfile:
    catalog_ref = _first_setting("TLS_PROFILES_REF")
    raw = resolve(catalog_ref) if catalog_ref else _first_setting("TLS_PROFILES")
    if not raw:
        raise TransportSecurityError("tls_profile_catalog_unavailable")
    chosen = _named(_parse_document(raw), name)
    source = "secret_catalog" if catalog_ref else "runtime_catalog"
    return SelectedProfile(name, source, True, chosen)
