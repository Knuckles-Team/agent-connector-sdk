"""Request-local ordered progress and bounded delivery."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from agent_connector_sdk.mcp.context import ToolExecutionContext
from agent_connector_sdk.mcp.progress import PROGRESS_SEND_TIMEOUT, OrderedProgress


def _context(token: str | None) -> ToolExecutionContext:
    return ToolExecutionContext(
        tenant_id="tenant",
        actor_id="actor",
        session_id="session",
        request_id="request",
        connector_id="connector",
        operation_id="operation",
        deadline=datetime.now(UTC) + timedelta(seconds=10),
        progress_token=token,
    )


@pytest.mark.asyncio
@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R050.8")
async def test_ordered_progress_serializes_and_bounds_delivery() -> None:
    assert PROGRESS_SEND_TIMEOUT == 5.0
    sent = []

    async def sender(token, progress):
        await asyncio.sleep(0)
        sent.append((token, progress))

    progress = OrderedProgress(
        _context("token"), sender, lambda text: text.replace("secret", "[redacted]")
    )
    await asyncio.gather(
        *(progress.update(1, total=3, message="secret") for _ in range(4))
    )
    await progress.update(2, total=3)
    assert [item.sequence for _, item in sent] == [1, 2]
    assert sent[0][1].message == "[redacted]"
    with pytest.raises(ValueError, match="decreased"):
        await progress.update(1, total=3)
    with pytest.raises(ValueError, match="total changed"):
        await progress.update(3, total=4)
    assert (await progress.finish()).sequence == 2
    with pytest.raises(ValueError, match="terminal"):
        await progress.update(3, total=3)
    no_token = OrderedProgress(_context(None), sender, lambda text: text)
    assert (await no_token.update(1)).sequence == 1
    assert len(sent) == 2
    assert await no_token.update(1, total=4) is None
    with pytest.raises(ValueError, match="total changed"):
        await no_token.update(2, total=5)

    async def slow_sender(token, item):
        await asyncio.Event().wait()

    slow = OrderedProgress(
        _context("token"), slow_sender, lambda text: text, send_timeout=0.01
    )
    with pytest.raises(TimeoutError):
        await slow.update(1)
    assert await slow.update(1) is None

    expired = _context("token").model_copy(
        update={"deadline": datetime.now(UTC) - timedelta(seconds=1)}
    )
    blocked = OrderedProgress(expired, sender, lambda text: text)
    with pytest.raises(TimeoutError, match="deadline"):
        await blocked.update(1)
    assert blocked.last is None
