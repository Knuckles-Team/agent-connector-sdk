"""Secret-reference-only command-line arguments (SCION-CONNECTOR-CONTROL-R014.4).

Moved from agent-utilities ``security.cli_secrets``. Secret material never
travels in a process argument: a CLI accepts only a bounded ``env://``,
``vault://`` or ``secret://`` reference and resolves it in memory. ``env://``
reads the SDK configuration; ``vault://`` and ``secret://`` resolve through the
SDK credential resolver as ``openbao://`` references. Error messages never
name the reference or the value.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from typing import Any

from scion_sdk.config import setting
from scion_sdk.credentials.resolution import resolve_secret_reference
from scion_sdk.credentials.resolver import CredentialResolver

__all__ = [
    "RuntimeSecretReferenceAction",
    "RuntimeSecretReferenceError",
    "resolve_runtime_secret_reference",
    "validate_runtime_secret_reference",
]

_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_STORE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./#@-]{0,511}$")
_MAX_REFERENCE_BYTES = 1_024
_MAX_SECRET_BYTES = 4 * 1024 * 1024


class RuntimeSecretReferenceError(ValueError):
    """A CLI secret reference is invalid or unavailable (never discloses it)."""


def _bounded_reference(reference: Any) -> str:
    rendered = str(reference or "").strip()
    if (
        not rendered
        or len(rendered.encode("utf-8")) > _MAX_REFERENCE_BYTES
        or any(character.isspace() or ord(character) < 32 for character in rendered)
    ):
        raise RuntimeSecretReferenceError("runtime secret reference is invalid")
    return rendered


def _validated_reference(reference: Any) -> tuple[str, str]:
    rendered = _bounded_reference(reference)
    scheme, separator, target = rendered.partition("://")
    if not separator or scheme not in {"env", "vault", "secret"}:
        raise RuntimeSecretReferenceError(
            "runtime secret reference must use env://, vault://, or secret://"
        )
    pattern = _ENV_NAME_RE if scheme == "env" else _STORE_KEY_RE
    if pattern.fullmatch(target) is None or ".." in target.split("/"):
        raise RuntimeSecretReferenceError("runtime secret reference is invalid")
    return scheme, rendered


def resolve_runtime_secret_reference(
    reference: Any, *, resolver: CredentialResolver | None = None
) -> str:
    """Resolve one validated CLI reference without disclosing it on failure."""
    scheme, rendered = _validated_reference(reference)
    cause: Exception | None = None
    value: object
    try:
        if scheme == "env":
            value = setting(rendered.removeprefix("env://"))
        else:
            target = rendered.partition("://")[2]
            value = resolve_secret_reference(f"openbao://{target}", resolver)
    except Exception as exc:  # re-raised below without the reference/value
        value = None
        cause = exc
    if not isinstance(value, str) or not value:
        raise RuntimeSecretReferenceError(
            "runtime secret reference is unavailable"
        ) from cause
    if len(value.encode("utf-8")) > _MAX_SECRET_BYTES or "\x00" in value:
        raise RuntimeSecretReferenceError("resolved runtime secret is invalid")
    return value


def validate_runtime_secret_reference(reference: Any) -> str:
    """Return one canonical reference without resolving its runtime value."""
    _scheme, rendered = _validated_reference(reference)
    return rendered


class RuntimeSecretReferenceAction(argparse.Action):
    """Argparse action that resolves a reference into the destination field."""

    def __call__(
        self,
        _parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        _option_string: str | None = None,
    ) -> None:
        if not isinstance(values, str):
            raise argparse.ArgumentError(self, "runtime secret reference is invalid")
        try:
            resolved = resolve_runtime_secret_reference(values)
        except RuntimeSecretReferenceError as exc:
            raise argparse.ArgumentError(self, str(exc)) from None
        setattr(namespace, self.dest, resolved)
