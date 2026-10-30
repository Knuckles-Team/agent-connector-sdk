"""Typed source client: models, cache, refusals and provenance (SCION-SCM-R001)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from typing import Any

import pytest
from pydantic import ValidationError

from agent_connector_sdk.source import (
    BlobCache,
    BlobRequest,
    ChangeEntry,
    CommitRequest,
    SourceClient,
    SourceRefusedError,
    TreeRequest,
)
from agent_connector_sdk.source.client import REFUSAL_REASONS

BLOB = b"hello world\n"
DIGEST = hashlib.sha256(BLOB).hexdigest()


class Backend:
    """A controlled served ``source.*`` backend."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.refuse: str | None = None
        self.revision = "r1"
        self.blob = BLOB

    async def call(self, operation: str, payload: Any) -> dict[str, Any]:
        self.calls.append((operation, dict(payload)))
        if self.refuse:
            return {"status": "refused", "reason": self.refuse}
        if operation == "tree":
            start = int(payload.get("continuation") or 0)
            names = ["a", "b", "c"][start : start + payload["page_size"]]
            more = start + payload["page_size"] < 3
            return {
                "status": "ok",
                "result": {
                    "revision": self.revision,
                    "entries": [
                        {"path": n, "mode": "100644", "digest": DIGEST, "size": 12}
                        for n in names
                    ],
                    "continuation": str(start + payload["page_size"]) if more else None,
                },
            }
        if operation == "blob":
            return {
                "status": "ok",
                "result": {
                    "revision": self.revision,
                    "content_base64": base64.b64encode(self.blob).decode(),
                },
            }
        if operation == "commit":
            return {
                "status": "ok",
                "result": {
                    "revision": "r2",
                    "receipt_ref": "receipt-1",
                    "outcomes": [{"path": "a", "outcome": "applied"}],
                },
            }
        return {"status": "ok", "result": {"entries": [], "revision": self.revision}}


def _commit(**changes: Any) -> CommitRequest:
    return CommitRequest(
        repository_id="repo",
        branch="work",
        base_revision="r1",
        message="m",
        changes=(ChangeEntry(path="a", operation="put", content_base64="aGk="),),
        **changes,
    )


@pytest.mark.spec("SCION-SCM-R001.1")
async def test_request_and_page_models_are_typed_and_frozen() -> None:
    request = TreeRequest(repository_id="repo", ref="main", path_prefix="src/")
    with pytest.raises(ValidationError):
        request.ref = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        TreeRequest(repository_id="repo", ref="main", untyped={"x": 1})  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        TreeRequest(repository_id="repo", ref="main", page_size=0)
    page = await SourceClient(Backend()).tree(request)
    with pytest.raises(ValidationError):
        page.entries = ()  # type: ignore[misc]
    assert page.entries[0].digest == DIGEST
    for method in (
        "tree",
        "blob",
        "diff",
        "history",
        "blame",
        "commit",
        "land",
        "revert",
    ):
        assert callable(getattr(SourceClient, method))


@pytest.mark.spec("SCION-SCM-R001.2")
async def test_cache_is_bounded_and_digest_checked() -> None:
    cache = BlobCache(max_entries=2, max_bytes=20)
    backend = Backend()
    client = SourceClient(backend, cache=cache)
    request = BlobRequest(repository_id="repo", ref="main", path="a", digest=DIGEST)
    cold = await client.blob(request)
    warm = await client.blob(request)
    assert (cold.cache, warm.cache) == ("miss", "hit")
    assert cold.digest == warm.digest == DIGEST and cold.content == warm.content
    assert len(backend.calls) == 1
    for index in range(3):
        cache.put(f"blob-{index}".encode())
    assert len(cache) <= 2 and cache.size_bytes <= 20
    assert cache.get(hashlib.sha256(b"blob-0").hexdigest()) is None
    cache.put(b"x" * 21)
    assert cache.size_bytes <= 20
    page = await client.tree(TreeRequest(repository_id="repo", ref="main", page_size=2))
    assert len(page.entries) == 2 and page.continuation
    rest = await client.tree(
        TreeRequest(
            repository_id="repo",
            ref="main",
            page_size=2,
            continuation=page.continuation,
        )
    )
    assert [e.path for e in rest.entries] == ["c"] and rest.continuation is None


@pytest.mark.spec("SCION-SCM-R001.2")
async def test_retry_reuses_operation_identity() -> None:
    backend = Backend()
    client = SourceClient(backend)
    first = await client.commit(_commit())
    again = await client.commit(_commit())
    assert first == again
    assert len(backend.calls) == 1
    assert backend.calls[0][1]["operation_id"] == first.provenance.operation_id
    other = await SourceClient(Backend()).commit(_commit())
    assert other.provenance.operation_id == first.provenance.operation_id
    keyed = await client.commit(_commit(change_id="change-7"))
    assert keyed.provenance.operation_id == "commit-change-7"


@pytest.mark.spec("SCION-SCM-R001.4")
async def test_refusals_are_typed_and_zero_effect() -> None:
    for reason in REFUSAL_REASONS:
        backend = Backend()
        backend.refuse = reason
        client = SourceClient(backend)
        with pytest.raises(SourceRefusedError) as error:
            await client.commit(_commit())
        assert error.value.reason == reason
        assert error.value.refusal.operation_id.startswith("commit-")
        assert not client._receipts

    backend = Backend()
    backend.refuse = "made_up"
    with pytest.raises(SourceRefusedError) as error:
        await SourceClient(backend).tree(TreeRequest(repository_id="r", ref="main"))
    assert error.value.reason == "transport_unavailable"

    class Down:
        async def call(self, operation: str, payload: Any) -> Any:
            raise RuntimeError("secret upstream")

    with pytest.raises(SourceRefusedError) as error:
        await SourceClient(Down()).commit(_commit())
    assert error.value.reason == "transport_unavailable"
    assert "secret" not in str(error.value)

    class Slow:
        async def call(self, operation: str, payload: Any) -> Any:
            await asyncio.sleep(1)

    with pytest.raises(SourceRefusedError) as error:
        await SourceClient(Slow(), deadline_seconds=0.01).tree(
            TreeRequest(repository_id="r", ref="main")
        )
    assert error.value.reason == "deadline_exceeded"

    big = Backend()
    client = SourceClient(big, max_blob_bytes=4)
    with pytest.raises(SourceRefusedError) as error:
        await client.blob(BlobRequest(repository_id="r", ref="main", path="a"))
    assert error.value.reason == "oversized"

    page = await SourceClient(Backend()).tree(
        TreeRequest(repository_id="r", ref="main", page_size=1)
    )
    with pytest.raises(SourceRefusedError) as error:
        await SourceClient(Backend()).tree(
            TreeRequest(
                repository_id="r2",
                ref="main",
                page_size=1,
                continuation=page.continuation,
            )
        )
    assert error.value.reason == "conflict"

    poisoned = Backend()
    client = SourceClient(poisoned)
    request = BlobRequest(repository_id="r", ref="main", path="a", digest=DIGEST)
    await client.blob(request)
    client.cache._items[DIGEST] = b"tampered"
    again = await client.blob(request)
    assert again.cache == "miss" and again.content == BLOB
    assert any(e.event == "mismatch" for e in client.cache.events)


@pytest.mark.spec("SCION-SCM-R001.5")
async def test_results_bind_provenance_without_secrets() -> None:
    backend = Backend()
    client = SourceClient(backend)
    page = await client.tree(TreeRequest(repository_id="repo", ref="main", page_size=2))
    assert page.provenance.repository_id == "repo"
    assert page.provenance.revision == "r1"
    assert page.provenance.page_size == 2
    assert len(page.provenance.request_digest) == 64
    receipt = await client.commit(_commit())
    assert receipt.provenance.receipt_ref == "receipt-1"
    assert receipt.provenance.operation_id.startswith("commit-")
    await client.blob(
        BlobRequest(repository_id="repo", ref="main", path="a", digest=DIGEST)
    )
    dumped = "".join(e.model_dump_json() for e in client.cache.events)
    assert "hello" not in dumped and DIGEST in dumped
    assert page.model_dump_json().count("secret") == 0
