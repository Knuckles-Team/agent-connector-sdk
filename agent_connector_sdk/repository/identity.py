"""Shared validation for repository transport identities."""

from pathlib import PurePosixPath

__all__: list[str] = []

_SHA256_PREFIX = "sha256:"


def _logical_path(value: str) -> str:
    """Return a normalized repository-relative POSIX path."""
    path = PurePosixPath(value)
    if not path.parts or value.startswith("/") or path.as_posix() != value:
        raise ValueError("repository path must be a normalized relative POSIX path")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("repository path must not contain empty or relative segments")
    return value


def _sha256_digest(value: str, *, field_name: str) -> str:
    """Return a canonical prefixed lowercase SHA-256 digest."""
    payload = value.removeprefix(_SHA256_PREFIX)
    if len(payload) != 64 or any(char not in "0123456789abcdef" for char in payload):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")
    return f"{_SHA256_PREFIX}{payload}"


def _immutable_git_id(value: str, *, field_name: str) -> str:
    """Return a Git SHA-1/SHA-256 object id, rejecting mutable ref names."""
    valid = len(value) in {40, 64} and all(char in "0123456789abcdef" for char in value)
    if not valid:
        raise ValueError(f"{field_name} must be an immutable lowercase Git object id")
    return value


def _validate_page(paths: list[str], next_cursor: str | None, *, label: str) -> None:
    """Enforce one page's shared invariants: unique paths, no empty continuation."""
    if len(paths) != len(set(paths)):
        raise ValueError(f"{label} paths must be unique")
    if not paths and next_cursor is not None:
        raise ValueError(f"an empty {label} cannot continue")
