"""Optional adapter callback for a worker's page-acceptance outcome."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from agent_connector_sdk.contracts import RecordPage


@runtime_checkable
class PageCompletionAdapter(Protocol):
    """Finalize staged adapter state after a worker accepts or rejects a page."""

    def finish_page(self, page: RecordPage, *, accepted: bool) -> None:
        """Record the outcome of the exact page returned by ``extract``."""
        ...


async def _accept_adapter_page[T](
    adapter: object,
    page: RecordPage,
    *,
    accept: Callable[[], Awaitable[T]],
) -> T:
    """Finish a staged page only after the worker verifies acceptance."""
    try:
        result = await accept()
    except BaseException:
        if isinstance(adapter, PageCompletionAdapter):
            adapter.finish_page(page, accepted=False)
        raise
    if isinstance(adapter, PageCompletionAdapter):
        adapter.finish_page(page, accepted=True)
    return result
