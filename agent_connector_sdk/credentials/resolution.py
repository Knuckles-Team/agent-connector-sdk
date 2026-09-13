"""Bounded secret resolution and the reference-only argparse action."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Any

import httpx

from agent_connector_sdk.credentials.openbao import OpenBaoCredentialResolver
from agent_connector_sdk.credentials.references import (
    SecretReferenceError,
    parse_secret_reference,
)
from agent_connector_sdk.credentials.resolver import (
    CompositeCredentialResolver,
    CredentialResolver,
    CredentialUnavailableError,
    EnvironmentCredentialResolver,
)

__all__ = [
    "SecretReferenceAction",
    "default_credential_resolver",
    "resolve_secret_reference",
]

_MAX_SECRET_BYTES = 4 * 1024 * 1024


def default_credential_resolver(
    *, http_client: httpx.Client | None = None
) -> CompositeCredentialResolver:
    """The environment resolver, plus OpenBao when ``OPENBAO_ADDR`` is set."""
    resolvers: dict[str, CredentialResolver] = {"env": EnvironmentCredentialResolver()}
    openbao = OpenBaoCredentialResolver.from_settings(http_client=http_client)
    if openbao is not None:
        resolvers["openbao"] = openbao
    return CompositeCredentialResolver(resolvers)


def resolve_secret_reference(
    reference: str, resolver: CredentialResolver | None = None
) -> str:
    """Parse ``reference`` and resolve it to a bounded value.

    Raises:
        SecretReferenceError: the reference is malformed.
        CredentialUnavailableError: the value is missing, oversized or holds NUL.
    """
    parsed = parse_secret_reference(reference)
    value = (resolver or default_credential_resolver()).resolve(parsed)
    if len(value.encode("utf-8")) > _MAX_SECRET_BYTES or "\x00" in value:
        raise CredentialUnavailableError("resolved secret is invalid")
    return value


class SecretReferenceAction(argparse.Action):
    """Accepts a reference on the command line and stores the resolved value."""

    def __init__(
        self,
        option_strings: Sequence[str],
        dest: str,
        resolver: CredentialResolver | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(option_strings, dest, **kwargs)
        self._resolver = resolver

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        _option_string: str | None = None,
    ) -> None:
        """Resolve the reference into ``namespace.<dest>``."""
        if not isinstance(values, str):
            raise argparse.ArgumentError(self, "secret reference is invalid")
        try:
            resolved = resolve_secret_reference(values, self._resolver)
        except (SecretReferenceError, CredentialUnavailableError) as exc:
            raise argparse.ArgumentError(self, str(exc)) from None
        setattr(namespace, self.dest, resolved)
