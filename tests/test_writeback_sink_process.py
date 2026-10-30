"""Process write-back sink: KG intelligence onto Camunda instances and ARIS models."""

from __future__ import annotations

import json
from typing import Any

import pytest

from scion_sdk.writeback_sinks.core import WritebackContext
from scion_sdk.writeback_sinks.sinks.process import (
    INTELLIGENCE_KEY,
    GraphComputeReader,
    ProcessSink,
    gather_intelligence,
    push_process_intelligence,
)

PROPS: dict[str, dict[str, Any]] = {
    "bpmn_process:invoice": {"type": "BusinessProcess", "key": "invoice"},
    "aris_model:M1": {"type": "BusinessProcess"},
    "wf:1": {"type": "Workflow", "name": "Invoice Workflow"},
    "agent:billing": {"type": "Agent", "name": "Billing Agent"},
    "policy:gdpr": {"type": "Policy", "name": "GDPR"},
    "incident:9": {"type": "Incident", "short_description": "Gateway timeout"},
    "bpmn_task:t1": {"type": "BusinessTask", "name": "Approve"},
    "do:inv": {"type": "DataObject", "name": "Invoice Record"},
    "concept:vat": {"type": "Concept", "name": "VAT"},
}
_PROCESS_OUT = [
    ("aris_model:M1", {"rel_type": "ALIGNED_WITH"}),
    ("policy:gdpr", {"rel_type": "governedBy"}),
]
_PROCESS_IN = [
    ("wf:1", {"rel_type": "REALIZES"}),
    ("incident:9", {"rel_type": "AFFECTS"}),
    ("bpmn_task:t1", {"rel_type": "PART_OF"}),
]
OUT = {
    "wf:1": [("agent:billing", {"rel_type": "ORCHESTRATES"})],
    "bpmn_task:t1": [
        ("do:inv", {"rel_type": "FLOWS_TO"}),
        ("concept:vat", {"rel_type": "MENTIONS"}),
    ],
}
EXPECTED = {
    "capabilities": ["Invoice Workflow (Billing Agent)"],
    "aligned_with": ["aris_model:M1"],
    "governance": ["GDPR"],
    "incidents": ["Gateway timeout"],
    "glossary_terms": ["VAT"],
    "data_objects": ["Invoice Record"],
}


class Reader:
    """In-memory graph whose ``process`` node carries all four intelligence sections."""

    def __init__(self, process: str = "bpmn_process:invoice") -> None:
        self.process = process

    def node_props(self, nid: str) -> dict[str, Any]:
        return PROPS.get(nid, {})

    def out_edges(self, nid: str) -> list[tuple[str, dict[str, Any]]]:
        return _PROCESS_OUT if nid == self.process else OUT.get(nid, [])

    def in_edges(self, nid: str) -> list[tuple[str, dict[str, Any]]]:
        return _PROCESS_IN if nid == self.process else []

    def process_nodes(self) -> list[tuple[str, dict[str, Any]]]:
        return [(self.process, PROPS[self.process])]


class Camunda:
    def __init__(
        self, instances: list[dict[str, str]] | None = None, fail: bool = False
    ):
        self.instances = [{"id": "PI-1"}] if instances is None else instances
        self.fail = fail
        self.vars: dict[str, Any] = {}
        self.writes: list[str] = []

    def list_process_instances(self, params: dict[str, str]) -> list[dict[str, str]]:
        assert params == {"processDefinitionKey": "invoice"}
        return self.instances

    def get_process_instance_variables(self, iid: str) -> dict[str, Any]:
        return self.vars.get(iid, {})

    def modify_process_instance_variables(self, iid: str, body: dict[str, Any]) -> None:
        if self.fail:
            raise RuntimeError("transport down")
        self.writes.append(iid)
        self.vars[iid] = {INTELLIGENCE_KEY: body["modifications"][INTELLIGENCE_KEY]}


class Aris:
    def __init__(self) -> None:
        self.attrs: dict[str, dict[str, str]] = {}

    def set_model_attributes(self, model_id: str, attributes: dict[str, str]) -> None:
        self.attrs[model_id] = attributes

    def list_model_attributes(self, model_id: str) -> dict[str, str]:
        return self.attrs.get(model_id, {})


def test_gather_collects_all_four_sections() -> None:
    assert gather_intelligence(Reader(), "bpmn_process:invoice") == EXPECTED


def test_camunda_write_is_hash_idempotent() -> None:
    client = Camunda()
    first = push_process_intelligence(Reader(), camunda_client=client)
    assert (first.enriched, client.writes) == (1, ["PI-1"])
    stored = json.loads(client.vars["PI-1"][INTELLIGENCE_KEY]["value"])
    assert {k: v for k, v in stored.items() if k != "_hash"} == EXPECTED
    second = push_process_intelligence(Reader(), camunda_client=client)
    assert (second.enriched, second.skipped, client.writes) == (0, 1, ["PI-1"])


def test_aris_write_sets_the_model_attribute_once() -> None:
    client = Aris()
    reader = Reader("aris_model:M1")
    assert push_process_intelligence(reader, aris_client=client).enriched == 1
    assert INTELLIGENCE_KEY in client.attrs["M1"]
    assert push_process_intelligence(reader, aris_client=client).skipped == 1


@pytest.mark.parametrize(
    ("client", "enriched", "skipped", "errors"),
    [
        (Camunda(instances=[]), 0, 1, 0),
        (Camunda(fail=True), 0, 0, 1),
    ],
)
def test_no_instance_skips_and_a_failing_client_does_not_abort(
    client: Camunda, enriched: int, skipped: int, errors: int
) -> None:
    result = push_process_intelligence(Reader(), camunda_client=client)
    assert (result.enriched, result.skipped, result.errors) == (
        enriched,
        skipped,
        errors,
    )


def test_dry_run_proposes_without_writing_and_no_client_is_a_no_op() -> None:
    client = Camunda()
    result = push_process_intelligence(Reader(), camunda_client=client, dry_run=True)
    assert result.proposals == [
        {"op": "write_intelligence", "process": "bpmn_process:invoice"}
    ]
    assert client.writes == []
    assert push_process_intelligence(Reader()).enriched == 0


class _GraphCompute:
    """``graph_compute`` view over the same in-memory graph."""

    def __init__(self, reader: Reader) -> None:
        self._r = reader

    def _get_node_properties(self, nid: str) -> dict[str, Any]:
        return self._r.node_props(nid)

    def out_edges(self, nid: str, data: bool) -> list[tuple[str, str, dict[str, Any]]]:
        return [(nid, t, p) for t, p in self._r.out_edges(nid)]

    def in_edges(self, nid: str, data: bool) -> list[tuple[str, str, dict[str, Any]]]:
        return [(s, nid, p) for s, p in self._r.in_edges(nid)]

    def nodes(self, data: bool) -> list[tuple[str, dict[str, Any]]]:
        return list(PROPS.items())


class _Engine:
    def __init__(self) -> None:
        self.graph_compute = _GraphCompute(Reader())


def test_sink_reads_the_engine_graph_and_pushes() -> None:
    reader = GraphComputeReader(_Engine())
    assert {pid for pid, _ in reader.process_nodes()} == {
        "bpmn_process:invoice",
        "aris_model:M1",
    }
    assert GraphComputeReader(object()).process_nodes() == []
    client = Camunda()
    result = ProcessSink().run(
        WritebackContext(engine=_Engine()),
        {"camunda_client": client, "process_ids": ["bpmn_process:invoice"]},
        dry_run=False,
    )
    assert (result.target, result.enriched, client.writes) == ("process", 1, ["PI-1"])
