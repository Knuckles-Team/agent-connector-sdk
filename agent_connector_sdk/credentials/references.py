"""The secret reference grammar.

``env://NAME``
    The value of environment variable ``NAME``.
``openbao://<mount>/<path>#<field>[@<version>]``
    Field ``field`` of the OpenBao KV v2 secret at ``<mount>/<path>``, optionally
    pinned to an exact version, for example
    ``openbao://apps/freshrss-agent#FRESHRSS_TOKEN``.

Error messages never contain the reference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

__all__ = ["SecretReference", "SecretReferenceError", "parse_secret_reference"]

_MAX_REFERENCE_BYTES = 1024
_ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
_OPENBAO_RE = re.compile(
    r"(?P<mount>[A-Za-z0-9][A-Za-z0-9_.-]{0,63})"
    r"/(?P<path>[A-Za-z0-9][A-Za-z0-9_./-]{0,383})"
    r"#(?P<field>[A-Za-z0-9_.-]{1,128})"
    r"(?:@(?P<version>[1-9][0-9]{0,8}))?"
)


class SecretReferenceError(ValueError):
    """A secret reference is malformed."""


@dataclass(frozen=True)
class SecretReference:
    """A parsed, validated secret reference."""

    scheme: Literal["env", "openbao"]
    target: str
    mount: str = ""
    path: str = ""
    field: str = ""
    version: int | None = None

    def render(self) -> str:
        """Return the canonical reference string."""
        return f"{self.scheme}://{self.target}"


def _bounded_text(reference: object) -> str:
    rendered = reference.strip() if isinstance(reference, str) else ""
    if (
        not rendered
        or len(rendered.encode("utf-8")) > _MAX_REFERENCE_BYTES
        or any(char.isspace() or ord(char) < 32 for char in rendered)
    ):
        raise SecretReferenceError("secret reference is invalid")
    return rendered


def _openbao_reference(target: str) -> SecretReference:
    match = _OPENBAO_RE.fullmatch(target)
    if match is None or any(
        segment in {"", ".", ".."} for segment in match["path"].split("/")
    ):
        raise SecretReferenceError("secret reference is invalid")
    version = match["version"]
    return SecretReference(
        scheme="openbao",
        target=target,
        mount=match["mount"],
        path=match["path"],
        field=match["field"],
        version=int(version) if version else None,
    )


def parse_secret_reference(reference: str) -> SecretReference:
    """Parse and validate one reference.

    Raises:
        SecretReferenceError: for anything other than a bounded ``env://`` or
            ``openbao://`` reference.
    """
    scheme, separator, target = _bounded_text(reference).partition("://")
    if separator and scheme == "env" and _ENV_NAME_RE.fullmatch(target):
        return SecretReference(scheme="env", target=target)
    if separator and scheme == "openbao":
        return _openbao_reference(target)
    raise SecretReferenceError(
        "secret reference must be env://NAME or openbao://mount/path#field"
    )
