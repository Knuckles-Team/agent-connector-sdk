"""Shared host policy validation for bounded earth-observation streams."""

import hashlib
import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from agent_connector_sdk.taxonomy.provider import _valid_identifier_batch


def _validate_stream_policy(
    tenant: str,
    name: str,
    connector: str,
    *,
    revision: str,
    identifiers: Sequence[str],
    batch_size: int,
) -> None:
    """Refuse missing authority, duplicate IDs and unbounded source pages."""
    if not all((tenant, name, connector, revision)) or not _valid_identifier_batch(
        identifiers, batch_size
    ):
        raise ValueError("invalid earth-observation stream policy")


def _checkpoint_offset(
    state: dict[str, Any] | None, *, key: str, binding: str, size: int
) -> int:
    if state is None:
        return 0
    if (
        set(state) != {key, "offset", "generation"}
        or state[key] != binding
        or not isinstance(state["generation"], str)
        or type(state["offset"]) is not int
        or not 0 <= state["offset"] < size
    ):
        raise ValueError("invalid stream checkpoint")
    return int(state["offset"])


def _stream_binding(values: Sequence[Any]) -> str:
    """Bind checkpoints to the complete host-admitted stream configuration."""
    return hashlib.sha256(
        json.dumps(values, separators=(",", ":")).encode()
    ).hexdigest()


async def _authorized_offset(
    authorize: Callable[[str, Any], Awaitable[bool]],
    *,
    tenant: str,
    context: Any,
    mode: str,
    state: dict[str, Any] | None,
    key: str,
    binding: str,
    size: int,
) -> int:
    if mode != "delta" or not await authorize(tenant, context):
        raise ValueError("access refused")
    return _checkpoint_offset(state, key=key, binding=binding, size=size)
