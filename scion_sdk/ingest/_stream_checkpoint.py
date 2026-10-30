"""Validate host-authorized generation checkpoints for unpaged source streams."""

from collections.abc import Awaitable, Callable
from typing import Any


async def _authorize_generation(
    authorize: Callable[[str, Any], Awaitable[bool]],
    *,
    tenant: str,
    context: Any,
    mode: str,
    state: dict[str, Any] | None,
    binding: str,
) -> None:
    if mode != "delta" or not await authorize(tenant, context):
        raise ValueError("access refused")
    if state is not None and (
        set(state) != {"binding", "generation"}
        or state["binding"] != binding
        or not isinstance(state["generation"], str)
    ):
        raise ValueError("invalid source checkpoint")
