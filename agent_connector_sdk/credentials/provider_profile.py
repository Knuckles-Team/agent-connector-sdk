"""Selected-provider credential profiles (SDK-CONNECTOR-CONTROL-R014.19).

Ported from ``agent_utilities.core.provider_runtime`` (the selection and
resolution half; child-process projection stays with arbora). A deployment
declares named provider profiles in ``PROVIDER_CONFIGS`` as JSON. A profile holds
only runtime *references* (``env://``, ``vault://``, ``secret://``) and a named
TLS selector, never values. The launcher selects one with
``AGENT_PROVIDER_PROFILE``; :func:`resolve_selected_provider_profile` resolves
its endpoint, credentials and selectors in memory and the TLS profile, and
:meth:`ResolvedProviderProfile.close` removes any materialized TLS files.
Failures carry a stable code and never the reference or the value.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from agent_connector_sdk.config import setting
from agent_connector_sdk.credentials.resolver import CredentialResolver
from agent_connector_sdk.credentials.runtime_references import (
    RuntimeSecretReferenceError,
    resolve_runtime_secret_reference,
    validate_runtime_secret_reference,
)
from agent_connector_sdk.tls.profile import ResolvedTLSProfile
from agent_connector_sdk.tls.resolve import resolve_tls_profile

__all__ = [
    "ProviderProfile",
    "ProviderProfileError",
    "ResolvedProviderProfile",
    "load_provider_profiles",
    "resolve_provider_profile",
    "resolve_selected_provider_profile",
]

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
_ALIAS_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_TLS_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})
_MAX_PROFILES = 256
_MAX_REFS = 16
_MAX_SELECTOR_BYTES = 262_144
_MAX_ENDPOINT_BYTES = 8_192


class ProviderProfileError(RuntimeError):
    """A provider profile is missing, invalid or unresolvable; ``str`` is a stable code."""


@dataclass(frozen=True)
class ProviderProfile:
    """One reference-only provider profile."""

    enabled: bool = False
    endpoint_ref: str | None = None
    credential_refs: Mapping[str, str] = field(default_factory=dict)
    selector_refs: Mapping[str, str] = field(default_factory=dict)
    tls_profile: str | None = None
    tls_profile_ref: str | None = None


@dataclass(repr=False)
class ResolvedProviderProfile:
    """Ephemeral resolved values with deterministic TLS-material cleanup."""

    endpoint: str | None = field(default=None, repr=False)
    credentials: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({}), repr=False
    )
    selectors: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({}), repr=False
    )
    tls: ResolvedTLSProfile | None = field(default=None, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def __repr__(self) -> str:
        return "<ResolvedProviderProfile redacted>"

    def close(self) -> None:
        """Drop every value and remove materialized TLS files; idempotent."""
        if self._closed:
            return
        self._closed = True
        trust, self.tls = self.tls, None
        self.endpoint = None
        self.credentials = MappingProxyType({})
        self.selectors = MappingProxyType({})
        if trust is not None:
            trust.cleanup()

    def __enter__(self) -> ResolvedProviderProfile:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _references(raw: Any) -> dict[str, str]:
    if raw in (None, ""):
        return {}
    if not isinstance(raw, Mapping) or len(raw) > _MAX_REFS:
        raise ProviderProfileError("provider_profiles_invalid")
    out: dict[str, str] = {}
    for alias, reference in raw.items():
        if not isinstance(alias, str) or _ALIAS_RE.fullmatch(alias) is None:
            raise ProviderProfileError("provider_profiles_invalid")
        try:
            out[alias] = validate_runtime_secret_reference(reference)
        except RuntimeSecretReferenceError:
            raise ProviderProfileError("provider_profiles_invalid") from None
    return out


def _profile(raw: Any) -> ProviderProfile:
    if not isinstance(raw, Mapping) or not set(raw) <= {
        "enabled",
        "endpoint_ref",
        "credential_refs",
        "selector_refs",
        "tls_profile",
        "tls_profile_ref",
    }:
        raise ProviderProfileError("provider_profiles_invalid")
    endpoint_ref = raw.get("endpoint_ref")
    tls_ref = raw.get("tls_profile_ref")
    tls_name = raw.get("tls_profile")
    try:
        endpoint_ref = (
            validate_runtime_secret_reference(endpoint_ref) if endpoint_ref else None
        )
        tls_ref = validate_runtime_secret_reference(tls_ref) if tls_ref else None
    except RuntimeSecretReferenceError:
        raise ProviderProfileError("provider_profiles_invalid") from None
    if tls_name is not None and (
        not isinstance(tls_name, str) or _TLS_NAME_RE.fullmatch(tls_name) is None
    ):
        raise ProviderProfileError("provider_profiles_invalid")
    profile = ProviderProfile(
        enabled=raw.get("enabled", False) is True,
        endpoint_ref=endpoint_ref,
        credential_refs=_references(raw.get("credential_refs")),
        selector_refs=_references(raw.get("selector_refs")),
        tls_profile=tls_name,
        tls_profile_ref=tls_ref,
    )
    if profile.tls_profile and profile.tls_profile_ref:
        raise ProviderProfileError("provider_profiles_invalid")
    if profile.endpoint_ref and not (profile.tls_profile or profile.tls_profile_ref):
        raise ProviderProfileError("provider_profiles_invalid")
    if set(profile.credential_refs) & set(profile.selector_refs):
        raise ProviderProfileError("provider_profiles_invalid")
    if profile.enabled and not (
        profile.endpoint_ref or profile.credential_refs or profile.selector_refs
    ):
        raise ProviderProfileError("provider_profiles_invalid")
    return profile


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for key, value in pairs:
        if key in parsed:
            raise ValueError("duplicate key")
        parsed[key] = value
    return parsed


def load_provider_profiles(
    raw: str | Mapping[str, Any] | None = None,
) -> dict[str, ProviderProfile]:
    """Parse and validate ``PROVIDER_CONFIGS`` (or ``raw``) into named profiles.

    Raises:
        ProviderProfileError: ``provider_profiles_invalid`` for any malformed input.
    """
    document: Any = setting("PROVIDER_CONFIGS", "") if raw is None else raw
    if isinstance(document, str):
        if not document.strip():
            return {}
        try:
            document = json.loads(document, object_pairs_hook=_no_duplicate_keys)
        except ValueError:
            raise ProviderProfileError("provider_profiles_invalid") from None
    if not isinstance(document, Mapping) or len(document) > _MAX_PROFILES:
        raise ProviderProfileError("provider_profiles_invalid")
    profiles: dict[str, ProviderProfile] = {}
    for name, body in document.items():
        if not isinstance(name, str) or _NAME_RE.fullmatch(name) is None:
            raise ProviderProfileError("provider_profiles_invalid")
        profiles[name] = _profile(body)
    return profiles


def _secure_endpoint(value: str) -> str:
    rendered = value.strip().rstrip("/")
    bad = (
        not rendered
        or len(rendered.encode("utf-8")) > _MAX_ENDPOINT_BYTES
        or any(c.isspace() or ord(c) < 32 for c in rendered)
    )
    try:
        parsed = urlsplit(rendered)
        port = parsed.port
    except ValueError:
        raise ProviderProfileError("provider_endpoint_invalid") from None
    host = (parsed.hostname or "").casefold()
    if (
        bad
        or parsed.scheme.casefold() not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65_535)
        or (parsed.scheme.casefold() == "http" and host not in _LOOPBACK)
    ):
        raise ProviderProfileError("provider_endpoint_invalid")
    return rendered


def _resolve_values(
    profile: ProviderProfile, resolver: CredentialResolver | None
) -> tuple[str | None, dict[str, str], dict[str, str]]:
    def one(reference: str) -> str:
        return resolve_runtime_secret_reference(reference, resolver=resolver)

    try:
        endpoint = (
            _secure_endpoint(one(profile.endpoint_ref))
            if profile.endpoint_ref
            else None
        )
        credentials = {a: one(r) for a, r in profile.credential_refs.items()}
        selectors: dict[str, str] = {}
        for alias, reference in profile.selector_refs.items():
            value = one(reference)
            if len(value.encode("utf-8")) > _MAX_SELECTOR_BYTES or any(
                c in value for c in "\x00\r\n"
            ):
                raise ProviderProfileError("provider_selector_invalid")
            selectors[alias] = value
    except ProviderProfileError:
        raise
    except Exception:
        raise ProviderProfileError("provider_runtime_reference_unavailable") from None
    return endpoint, credentials, selectors


def resolve_provider_profile(
    name: str,
    *,
    profiles: Mapping[str, ProviderProfile] | None = None,
    resolver: CredentialResolver | None = None,
) -> ResolvedProviderProfile:
    """Resolve one enabled profile at its exact runtime boundary.

    Raises:
        ProviderProfileError: ``provider_profile_invalid``,
            ``provider_profile_unavailable``, ``provider_profile_disabled``,
            ``provider_endpoint_invalid``, ``provider_selector_invalid``,
            ``provider_runtime_reference_unavailable`` or
            ``provider_tls_profile_invalid``.
    """
    if _NAME_RE.fullmatch(str(name or "").strip()) is None:
        raise ProviderProfileError("provider_profile_invalid")
    name = name.strip()
    available = load_provider_profiles() if profiles is None else profiles
    profile = available.get(name)
    if profile is None:
        raise ProviderProfileError("provider_profile_unavailable")
    if not profile.enabled:
        raise ProviderProfileError("provider_profile_disabled")
    endpoint, credentials, selectors = _resolve_values(profile, resolver)
    tls = None
    if profile.tls_profile or profile.tls_profile_ref:
        try:
            tls = resolve_tls_profile(
                name,
                profile_name=profile.tls_profile,
                profile_ref=profile.tls_profile_ref,
                resolver=resolver,
            )
        except Exception:
            raise ProviderProfileError("provider_tls_profile_invalid") from None
    return ResolvedProviderProfile(
        endpoint=endpoint,
        credentials=MappingProxyType(credentials),
        selectors=MappingProxyType(selectors),
        tls=tls,
    )


def resolve_selected_provider_profile(
    *,
    profiles: Mapping[str, ProviderProfile] | None = None,
    resolver: CredentialResolver | None = None,
) -> ResolvedProviderProfile:
    """Resolve the profile the launcher selected with ``AGENT_PROVIDER_PROFILE``.

    Raises:
        ProviderProfileError: ``provider_profile_not_selected`` when unset, else
            as :func:`resolve_provider_profile`.
    """
    selected = setting("AGENT_PROVIDER_PROFILE")
    if selected in (None, ""):
        raise ProviderProfileError("provider_profile_not_selected")
    return resolve_provider_profile(str(selected), profiles=profiles, resolver=resolver)
