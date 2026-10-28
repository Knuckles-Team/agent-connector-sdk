"""SDK-local read-time check boundary; engine composition is separate."""

from __future__ import annotations

from datetime import UTC, datetime

import anyio
import pytest
from pydantic import ValidationError

from agent_connector_sdk.ingest.sources import IngestSourceDeclaration
from agent_connector_sdk.ports.access_check import (
    AccessCheckAnswer,
    AccessCheckPort,
    BoundedAccessCheck,
)


class _Source:
    def __init__(self, answer: AccessCheckAnswer | None = None) -> None:
        self.answer = answer
        self.calls = 0

    async def check(
        self, principal: str, record_refs: tuple[str, ...]
    ) -> AccessCheckAnswer:
        self.calls += 1
        if self.answer is None:
            await anyio.sleep_forever()
            raise AssertionError("unreachable")
        return self.answer


@pytest.mark.spec("SDK-SOURCE-INGEST-R805.7")
async def test_timeout_denies_the_complete_bounded_batch() -> None:
    source: AccessCheckPort = _Source()
    answer = await BoundedAccessCheck(source, timeout_seconds=0.02).check(
        "actor", ("a", "b")
    )
    assert answer.allowed == ()
    assert answer.denied == ("a", "b")
    assert answer.checked_at.utcoffset() is not None


@pytest.mark.spec("SDK-SOURCE-INGEST-R805.7")
async def test_provider_partition_must_match_requested_refs_exactly() -> None:
    now = datetime.now(UTC)
    source = _Source(AccessCheckAnswer(("a",), ("b",), now))
    boundary = BoundedAccessCheck(source)
    assert await boundary.check("actor", ("a", "b")) == source.answer
    for answer in (
        AccessCheckAnswer(("a",), (), now),
        AccessCheckAnswer(("a", "b"), ("b",), now),
        AccessCheckAnswer(("a",), ("other",), now),
    ):
        source.answer = answer
        with pytest.raises(ValueError):
            await boundary.check("actor", ("a", "b"))
    calls = source.calls
    for refs in (("a", "a"), tuple(str(i) for i in range(201))):
        with pytest.raises(ValueError):
            await boundary.check("actor", refs)
    assert source.calls == calls


@pytest.mark.spec("SDK-SOURCE-INGEST-R805.7")
def test_source_declaration_exposes_explicit_access_mode() -> None:
    document = {
        "connector": "example",
        "sources": [
            {
                "source_id": "docs",
                "record_type": "document",
                "tools": ["list"],
                "id_field": "id",
                "access_mode": "checked_at_read",
            }
        ],
    }
    declaration = IngestSourceDeclaration.model_validate(document)
    assert declaration.sources[0].access_mode == "checked_at_read"
    assert (
        IngestSourceDeclaration.model_validate_json(declaration.model_dump_json())
        .sources[0]
        .access_mode
        == "checked_at_read"
    )
    document["sources"][0]["access_mode"] = "unknown"
    with pytest.raises(ValidationError):
        IngestSourceDeclaration.model_validate(document)
