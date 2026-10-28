"""Request-cache scoping, lifecycle and admission."""

from datetime import UTC, datetime, timedelta

import pytest

from agent_connector_sdk.mcp.context import ToolExecutionContext
from agent_connector_sdk.mcp.request_cache import (
    DEFAULT_REQUEST_CACHE_ENTRIES,
    RequestCache,
    RequestCacheKey,
)


def _context(request: str, *, expired: bool = False) -> ToolExecutionContext:
    return ToolExecutionContext(
        tenant_id="tenant",
        actor_id="actor",
        session_id="session",
        request_id=request,
        connector_id="connector",
        operation_id="operation",
        deadline=datetime.now(UTC) + timedelta(seconds=-1 if expired else 60),
    )


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R050.9")
def test_request_cache_is_bounded_scoped_and_expires() -> None:
    assert DEFAULT_REQUEST_CACHE_ENTRIES == 128
    first = RequestCache(
        _context("first"), lambda value: value != "denied", max_entries=2
    )
    second = RequestCache(_context("second"), lambda value: True, max_entries=2)
    a = RequestCacheKey("a", "scope")
    b = RequestCacheKey("b", "scope")
    c = RequestCacheKey("c", "scope")
    other_scope = RequestCacheKey("a", "other")
    with pytest.raises(ValueError, match="carry digests"):
        first.get("raw arguments")
    first.put(a, "one")
    first.put(b, "two")
    assert first.get(a) == "one"
    assert second.get(a) is None and first.get(other_scope) is None
    first.put(c, "three")
    assert first.get(b) is None and first.get(a) == "one"
    with pytest.raises(ValueError, match="not admitted"):
        first.put(b, "denied")
    assert first.get(b) is None
    first.close()
    with pytest.raises(ValueError, match="closed"):
        first.get(a)
    expired = RequestCache(_context("expired", expired=True), lambda value: True)
    with pytest.raises(TimeoutError, match="deadline"):
        expired.put(a, "one")
    with pytest.raises(ValueError, match="closed"):
        expired.get(a)
    with pytest.raises(ValueError):
        RequestCacheKey(" ", "scope")


def test_deadline_is_rechecked_after_admission(monkeypatch) -> None:
    from agent_connector_sdk.mcp import request_cache

    context = _context("during-admission")
    current = [context.deadline - timedelta(seconds=1)]

    class Clock:
        @staticmethod
        def now(_zone):
            return current[0]

    def admit(_value):
        current[0] = context.deadline
        return True

    monkeypatch.setattr(request_cache, "datetime", Clock)
    cache = RequestCache(context, admit)
    with pytest.raises(TimeoutError):
        cache.put(RequestCacheKey("a", "scope"), "value")
    with pytest.raises(ValueError, match="closed"):
        cache.get(RequestCacheKey("a", "scope"))
