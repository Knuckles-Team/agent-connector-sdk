"""Ingest under an engine-accepted contract (fake engine)."""

from __future__ import annotations

import pytest
from epistemic_graph.generated.source_ingestion import (
    SourceMappingKind,
    SourceMappingReceipt,
)
from ingest_fakes import SinkBackedEngine

from scion_sdk.ingest import (
    AcceptedContract,
    ChangeSet,
    ContractEvidence,
    ContractNotAcceptedError,
    Entity,
    IngestBinding,
    IngestError,
    KnowledgeIngest,
    NestedMapping,
    UndeclaredNestedValueError,
    contract_evidence,
)
from scion_sdk.ingest.contract import ContractTransport, require_accepted
from scion_sdk.ingest.request import build_request

DIGEST = "a" * 64
IRI = "contract:demo-mcp"


def _binding(**over: object) -> IngestBinding:
    fields: dict[str, object] = {
        "connector": "demo-mcp",
        "stream": "demo",
        "contract_iri": IRI,
        "contract_revision": "3",
        "contract_digest": DIGEST,
        "cursor_policy_iri": "policy:demo-cursor",
        "nested": {"Item.owner": NestedMapping("Person", "ownedBy")},
    }
    fields.update(over)
    return IngestBinding(**fields)  # type: ignore[arg-type]


class _Engine(SinkBackedEngine):
    """Fake engine: an in-memory sink plus the accepted-contract read."""

    def __init__(self, accepted: AcceptedContract | None) -> None:
        super().__init__()
        self.accepted = accepted
        self.refuse: str | None = None

    async def accepted_contract(self, connector: str) -> AcceptedContract | None:
        return self.accepted

    def _gate(self) -> None:
        if self.refuse:
            raise RuntimeError(self.refuse)

    async def store_blob(self, data: bytes) -> str:
        return "0" * 64


def _changes() -> ChangeSet:
    return ChangeSet(
        entities=(Entity("i:1", "Item", {"name": "x", "owner": {"name": "ann"}}),)
    )


@pytest.mark.spec("SCION-SOURCE-INGEST-R017.1")
def test_binding_carries_contract_iri() -> None:
    binding = _binding()
    assert (binding.contract_iri, binding.contract_revision) == (IRI, "3")
    request = build_request(
        binding, ChangeSet(entities=(Entity("i:1", "Item"),)), previous=None
    )
    assert request.records[0].mapping_reference == f"{IRI}#Item"
    with pytest.raises(ValueError):
        _binding(contract_iri="contract:other")


def test_nested_values_become_relationships() -> None:
    request = build_request(_binding(), _changes(), previous=None)
    by_id = {r.record_id: r for r in request.records}
    assert by_id["i:1"].payload == {"name": "x"}
    assert by_id["i:1/owner"].payload == {"name": "ann"}
    assert [r.relation_reference for r in request.relationships] == [
        "connector:demo-mcp#relations/Item/ownedBy"
    ]
    assert request.provider_checkpoint.position["cursor_policy"] == "policy:demo-cursor"


@pytest.mark.spec("SCION-SOURCE-INGEST-R017.3")
async def test_submit_checks_accepted_contract() -> None:
    engine = _Engine(AcceptedContract(DIGEST, "3"))
    await KnowledgeIngest(engine).submit(_binding(), _changes())
    assert len(engine.requests) == 1


@pytest.mark.spec("SCION-SOURCE-INGEST-R017.4")
async def test_refusals_keep_checkpoint() -> None:
    for accepted in (None, AcceptedContract("b" * 64), AcceptedContract(DIGEST, "9")):
        engine = _Engine(accepted)
        with pytest.raises(ContractNotAcceptedError, match="contract_not_accepted"):
            await KnowledgeIngest(engine).submit(_binding(), _changes())
        assert engine.requests == []
    engine = _Engine(AcceptedContract(DIGEST, "3"))
    bare = _binding(nested={})
    with pytest.raises(UndeclaredNestedValueError, match="undeclared_nested_value"):
        await KnowledgeIngest(engine).submit(bare, _changes())
    assert engine.requests == []
    for code in ("UNKNOWN_MAPPING_REFERENCE", "CURSOR_POLICY_VIOLATION"):
        engine.refuse = f"{code}: nope"
        with pytest.raises(IngestError, match=code):
            await KnowledgeIngest(engine).submit(_binding(), _changes())
    status = await engine.source_status("demo-mcp", "demo")
    assert status.accepted_checkpoint is None


@pytest.mark.spec("SCION-SOURCE-INGEST-R017.5")
async def test_report_matches_engine_receipt() -> None:
    engine = _Engine(AcceptedContract(DIGEST, "3"))
    receipt = await KnowledgeIngest(engine).submit(_binding(), _changes())
    catalog = _catalog()
    mapping = SourceMappingReceipt(
        catalog=catalog,
        connector_pack_digest=DIGEST,
        kind=SourceMappingKind.ENTITY,
        mapping_digest="c" * 64,
        mapping_reference=f"{IRI}#Item",
    )
    bound = receipt.model_copy(update={"mappings": [mapping]})
    evidence = contract_evidence(_binding(), bound)
    assert (evidence.iri, evidence.revision, evidence.digest) == (IRI, "3", DIGEST)
    assert evidence.mapping_digests == ("c" * 64,)
    wrong = mapping.model_copy(update={"connector_pack_digest": "d" * 64})
    with pytest.raises(IngestError):
        contract_evidence(_binding(), receipt.model_copy(update={"mappings": [wrong]}))


def _catalog():  # type: ignore[no-untyped-def]
    from epistemic_graph.generated._shared import McpCatalogSnapshotBinding

    return McpCatalogSnapshotBinding(
        authorization_scope_digest="e" * 64,
        catalog_generation=1,
        child_connection_generation=1,
        configuration_revision=1,
        snapshot_digest="f" * 64,
    )


async def test_transport_protocol_and_evidence_type() -> None:
    engine = _Engine(AcceptedContract(DIGEST, "3"))
    assert isinstance(engine, ContractTransport)
    await require_accepted(engine, _binding())
    await require_accepted(object(), IngestBinding(connector="demo-mcp", stream="s"))
    assert ContractEvidence.__name__ == "ContractEvidence"
