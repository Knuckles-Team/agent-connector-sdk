"""Typed outbound credentials, looked up by source name.

A caller asks for the credential of a source (``"github"``, ``"reddit"``) and
gets a :class:`SourceCredential` it applies to a request through
:meth:`SourceCredential.materialize`. Descriptors hold only secret references
(``env://`` or ``openbao://``); values are resolved through a
:class:`~agent_connector_sdk.credentials.resolver.CredentialResolver`.

Descriptor map, read from the ``SOURCE_CREDENTIALS`` setting as a JSON object::

    {
      "x":      {"type": "cookie_session", "secret": "openbao://apps/x#session"},
      "github": {"type": "api_key", "secret": "env://GITHUB_TOKEN", "prefix": "token "},
      "reddit": {"type": "oauth2", "secret": "openbao://apps/reddit#token",
                 "token_url": "https://www.reddit.com/api/v1/access_token",
                 "client_id": "abc", "client_secret_secret": "openbao://apps/reddit#cs"}
    }

A source with no descriptor, or with a descriptor that cannot be built,
resolves to the keyless credential, so keyless backends need no configuration.
"""

from __future__ import annotations

import abc
import base64
import json
import logging
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, Field

from agent_connector_sdk.config import setting
from agent_connector_sdk.credentials.references import (
    SecretReferenceError,
    parse_secret_reference,
)
from agent_connector_sdk.credentials.resolution import resolve_secret_reference
from agent_connector_sdk.credentials.resolver import CredentialResolver

__all__ = [
    "CREDENTIAL_TYPES",
    "ApiKeyCredential",
    "AuthMaterial",
    "BasicAuthCredential",
    "CookieSessionCredential",
    "KeylessCredential",
    "OAuth2Credential",
    "SourceCredential",
    "SourceCredentials",
    "build_credential",
]

logger = logging.getLogger(__name__)

#: An OAuth token is refreshed this many seconds before it expires.
EXPIRY_SKEW_S = 30.0

#: Posts a token request: ``(url, form, basic_auth) -> JSON payload``.
TokenPoster = Callable[[str, dict[str, str], tuple[str, str] | None], Mapping[str, Any]]


class AuthMaterial(BaseModel):
    """Headers, query parameters and cookies one credential contributes."""

    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, str] = Field(default_factory=dict)
    cookies: dict[str, str] = Field(default_factory=dict)

    def merged_into(
        self,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
    ) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        """``(headers, params, cookies)`` with this material on top."""
        return (
            {**(headers or {}), **self.headers},
            {**(params or {}), **self.params},
            {**(cookies or {}), **self.cookies},
        )


def _resolve(resolver: CredentialResolver | None, reference: Any) -> str | None:
    """Resolve one reference; ``None`` when absent or no resolver is given."""
    if not reference:
        return None
    if not isinstance(reference, str):
        raise ValueError("source credential must use a secret reference")
    try:
        parse_secret_reference(reference)
    except SecretReferenceError as exc:
        raise ValueError("source credential must use a secret reference") from exc
    if resolver is None:
        return None
    return resolve_secret_reference(reference, resolver)


class SourceCredential(abc.ABC):
    """A typed credential that can be applied to a request and refreshed."""

    type_name: ClassVar[str] = "base"

    @abc.abstractmethod
    def materialize(self) -> AuthMaterial:
        """The request material to apply."""
        raise NotImplementedError  # ABSTRACT-OK

    @abc.abstractmethod
    def is_present(self) -> bool:
        """Whether this credential carries usable material."""
        raise NotImplementedError  # ABSTRACT-OK

    def refresh(self) -> None:  # noqa: B027 - static credentials need no refresh
        """Refresh the credential in place."""

    @classmethod
    @abc.abstractmethod
    def from_descriptor(
        cls, descriptor: Mapping[str, Any], resolver: CredentialResolver | None
    ) -> SourceCredential:
        """Build the credential from a descriptor."""
        raise NotImplementedError  # ABSTRACT-OK


class KeylessCredential(SourceCredential):
    """Present, and contributes nothing."""

    type_name: ClassVar[str] = "none"

    def materialize(self) -> AuthMaterial:
        return AuthMaterial()

    def is_present(self) -> bool:
        return True

    @classmethod
    def from_descriptor(
        cls, descriptor: Mapping[str, Any], resolver: CredentialResolver | None
    ) -> KeylessCredential:
        return cls()


class ApiKeyCredential(SourceCredential):
    """A key applied as a header (default ``Authorization: Bearer``) or query parameter."""

    type_name: ClassVar[str] = "api_key"

    def __init__(
        self,
        key: str | None,
        *,
        placement: str = "header",
        name: str = "Authorization",
        prefix: str = "Bearer ",
    ) -> None:
        if placement not in {"header", "query"}:
            raise ValueError("api_key placement must be header or query")
        self.key = key
        self.placement = placement
        self.name = name
        self.prefix = prefix

    def materialize(self) -> AuthMaterial:
        if not self.key:
            return AuthMaterial()
        value = {self.name: f"{self.prefix}{self.key}"}
        if self.placement == "query":
            return AuthMaterial(params=value)
        return AuthMaterial(headers=value)

    def is_present(self) -> bool:
        return bool(self.key)

    @classmethod
    def from_descriptor(
        cls, descriptor: Mapping[str, Any], resolver: CredentialResolver | None
    ) -> ApiKeyCredential:
        return cls(
            _resolve(resolver, descriptor.get("secret")),
            placement=descriptor.get("placement", "header"),
            name=descriptor.get("name", "Authorization"),
            prefix=descriptor.get("prefix", "Bearer "),
        )


def _parse_cookies(raw: str | None) -> dict[str, str]:
    """Cookies from a JSON object or a ``name=value; name2=value2`` string."""
    raw = (raw or "").strip()
    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
    pairs = (part.strip().split("=", 1) for part in raw.split(";") if "=" in part)
    return {name.strip(): value.strip() for name, value in pairs}


class CookieSessionCredential(SourceCredential):
    """A cookie jar applied as the ``Cookie`` header and the client cookie jar."""

    type_name: ClassVar[str] = "cookie_session"

    def __init__(self, cookies: Mapping[str, str] | None) -> None:
        self.cookies = dict(cookies or {})

    def materialize(self) -> AuthMaterial:
        if not self.cookies:
            return AuthMaterial()
        header = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        return AuthMaterial(headers={"Cookie": header}, cookies=dict(self.cookies))

    def is_present(self) -> bool:
        return bool(self.cookies)

    @classmethod
    def from_descriptor(
        cls, descriptor: Mapping[str, Any], resolver: CredentialResolver | None
    ) -> CookieSessionCredential:
        if "cookies" in descriptor:
            raise ValueError("inline cookie material is unsupported")
        return cls(_parse_cookies(_resolve(resolver, descriptor.get("secret"))))


class BasicAuthCredential(SourceCredential):
    """HTTP Basic auth as an ``Authorization: Basic`` header."""

    type_name: ClassVar[str] = "basic"

    def __init__(self, username: str | None, password: str | None) -> None:
        self.username = username
        self.password = password

    def materialize(self) -> AuthMaterial:
        if not self.username:
            return AuthMaterial()
        token = base64.b64encode(f"{self.username}:{self.password or ''}".encode())
        return AuthMaterial(headers={"Authorization": f"Basic {token.decode()}"})

    def is_present(self) -> bool:
        return bool(self.username)

    @classmethod
    def from_descriptor(
        cls, descriptor: Mapping[str, Any], resolver: CredentialResolver | None
    ) -> BasicAuthCredential:
        username = descriptor.get("username") or _resolve(
            resolver, descriptor.get("username_secret")
        )
        return cls(username, _resolve(resolver, descriptor.get("password_secret")))


def _default_token_poster(tls_service: str, timeout: float) -> TokenPoster:
    def post(
        url: str, form: dict[str, str], auth: tuple[str, str] | None
    ) -> Mapping[str, Any]:
        from agent_connector_sdk.tls.resolve import resolve_tls_profile

        trust = resolve_tls_profile(tls_service)
        try:
            with httpx.Client(timeout=timeout, **trust.httpx_kwargs()) as client:
                response = client.post(url, data=form, auth=auth)
                response.raise_for_status()
                return response.json()
        finally:
            trust.cleanup()

    return post


class OAuth2Credential(SourceCredential):
    """An OAuth2 access token that refreshes itself with the refresh-token grant.

    ``materialize`` refreshes when the token is missing or within
    :data:`EXPIRY_SKEW_S` of expiry. A failed refresh contributes no header.
    """

    type_name: ClassVar[str] = "oauth2"

    def __init__(
        self,
        access_token: str | None = None,
        refresh_token: str | None = None,
        *,
        token_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        scope: str | None = None,
        expires_in: float | None = None,
        tls_service: str = "oauth2-token",
        timeout: float = 15.0,
        post: TokenPoster | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self._clock = clock
        self._expires_at = clock() + expires_in if expires_in else 0.0
        self._post = post or _default_token_poster(tls_service, timeout)
        self._lock = threading.Lock()

    def _needs_refresh(self) -> bool:
        if not self.access_token:
            return True
        return bool(self._expires_at) and (
            self._clock() >= self._expires_at - EXPIRY_SKEW_S
        )

    def refresh(self) -> None:
        with self._lock:
            if not (self.refresh_token and self.token_url and self.client_id):
                return
            form = {
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
            }
            if self.scope:
                form["scope"] = self.scope
            auth = (
                (self.client_id, self.client_secret)
                if self.client_secret is not None
                else None
            )
            payload = self._post(self.token_url, form, auth)
            self.access_token = str(payload["access_token"])
            self.refresh_token = payload.get("refresh_token") or self.refresh_token
            self._expires_at = self._clock() + float(payload.get("expires_in", 3600))

    def materialize(self) -> AuthMaterial:
        if self._needs_refresh():
            try:
                self.refresh()
            except Exception as exc:
                logger.warning("OAuth2 refresh failed (%s)", type(exc).__name__)
        if not self.access_token:
            return AuthMaterial()
        return AuthMaterial(headers={"Authorization": f"Bearer {self.access_token}"})

    def is_present(self) -> bool:
        return bool(self.access_token or self.refresh_token)

    @classmethod
    def from_descriptor(
        cls, descriptor: Mapping[str, Any], resolver: CredentialResolver | None
    ) -> OAuth2Credential:
        if "refresh_token" in descriptor:
            raise ValueError("inline refresh-token material is unsupported")
        if "verify" in descriptor or "allow_insecure" in descriptor:
            raise ValueError("TLS verification cannot be turned off")
        raw = _resolve(resolver, descriptor.get("secret"))
        access_token, refresh_token, expires_in = raw, None, None
        if raw and raw.strip().startswith("{"):
            token = json.loads(raw)
            access_token = token.get("access_token")
            refresh_token = token.get("refresh_token")
            expires_in = float(token["expires_in"]) if token.get("expires_in") else None
        refresh_ref = descriptor.get("refresh_token_secret")
        if refresh_ref:
            refresh_token = _resolve(resolver, refresh_ref)
        return cls(
            access_token,
            refresh_token,
            token_url=descriptor.get("token_url"),
            client_id=descriptor.get("client_id"),
            client_secret=_resolve(resolver, descriptor.get("client_secret_secret")),
            scope=descriptor.get("scope"),
            expires_in=expires_in,
            tls_service=str(descriptor.get("tls_service") or "oauth2-token"),
        )


CREDENTIAL_TYPES: dict[str, type[SourceCredential]] = {
    kind.type_name: kind
    for kind in (
        KeylessCredential,
        ApiKeyCredential,
        CookieSessionCredential,
        BasicAuthCredential,
        OAuth2Credential,
    )
}


def build_credential(
    descriptor: Mapping[str, Any] | None, resolver: CredentialResolver | None = None
) -> SourceCredential:
    """Build the credential named by ``descriptor["type"]`` (keyless when absent).

    Raises:
        KeyError: ``type`` is not a registered credential kind.
    """
    type_name = (descriptor or {}).get("type", "none")
    kind = CREDENTIAL_TYPES.get(type_name)
    if kind is None:
        raise KeyError(
            f"unknown credential type {type_name!r}; "
            f"available: {', '.join(sorted(CREDENTIAL_TYPES))}"
        )
    return kind.from_descriptor(descriptor or {}, resolver)


def _configured_descriptors() -> dict[str, dict[str, Any]]:
    raw = setting("SOURCE_CREDENTIALS", default="") or ""
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        logger.warning("SOURCE_CREDENTIALS is not valid JSON; ignoring it")
        return {}
    if not isinstance(parsed, dict):
        logger.warning("SOURCE_CREDENTIALS is not a JSON object; ignoring it")
        return {}
    return {str(k): dict(v) for k, v in parsed.items() if isinstance(v, dict)}


class SourceCredentials:
    """Thread-safe, cached credentials by source name.

    Credentials are built on first use. Stateful credentials refresh in place,
    so the cache holds the live object.
    """

    def __init__(
        self,
        descriptors: Mapping[str, Mapping[str, Any]] | None = None,
        resolver: CredentialResolver | None = None,
    ) -> None:
        if descriptors is None:
            descriptors = _configured_descriptors()
        self._descriptors = {k: dict(v) for k, v in descriptors.items()}
        self._resolver = resolver
        self._cache: dict[str, SourceCredential] = {}
        self._lock = threading.Lock()

    def register(self, source: str, descriptor: Mapping[str, Any]) -> None:
        """Add or replace the descriptor for ``source``."""
        with self._lock:
            self._descriptors[source] = dict(descriptor)
            self._cache.pop(source, None)

    def get(self, source: str) -> SourceCredential:
        """The credential for ``source``; keyless when unknown or unbuildable."""
        with self._lock:
            cached = self._cache.get(source)
            if cached is not None:
                return cached
            descriptor = self._descriptors.get(source)
            try:
                credential = build_credential(descriptor, self._resolver)
            except Exception as exc:
                logger.warning(
                    "credential for %r is unusable (%s); treating it as keyless",
                    source,
                    type(exc).__name__,
                )
                credential = KeylessCredential()
            self._cache[source] = credential
            return credential

    def available(self, source: str) -> bool:
        """Whether ``source`` has a real, present (not keyless) credential."""
        credential = self.get(source)
        return credential.type_name != KeylessCredential.type_name and (
            credential.is_present()
        )

    def status(self) -> dict[str, dict[str, Any]]:
        """``{source: {type, available}}``; never secret values."""
        return {
            source: {
                "type": self.get(source).type_name,
                "available": self.available(source),
            }
            for source in sorted(self._descriptors)
        }
