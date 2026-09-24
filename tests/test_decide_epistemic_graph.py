"""The EG-backed connector decision runner (EH-042/043): decide, record, or
fall back -- never raise.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest

from agent_connector_sdk.decide import Option
from agent_connector_sdk.decide.epistemic_graph import (
    DEFAULT_SYNC_TIMEOUT_S,
    DecideTransport,
    DecideUnavailable,
    EpistemicGraphDecisionRunner,
    GeneratedTransport,
    _generated,
)
from agent_connector_sdk.decide.outcome import Reading, read_batch, request_for, sampled
from agent_connector_sdk.decide.points import (
    CONNECTOR_TOOL,
    CONNECTOR_WRITEBACK,
    EMPTY_BINDINGS,
    POINTS,
    Binding,
    Bindings,
    DecisionPoint,
    LogMode,
    StaticBindings,
    point,
)

#: EG's own ``query`` module always has SOME sender (a much older, unrelated
#: method) -- used to prove ``_generated``'s positive path without coupling
#: this test to ``Decide``'s own landing status in the installed EG version.
_A_SENDER_ALWAYS_PUBLISHED = "send_cypher_query"

OPTIONS = [Option("search"), Option("get")]

_SCHEMA = {
    "component_id": "decide.schema.au.connector.tool",
    "kind": "feature_schema",
    "definition_digest": "sha256:" + "0" * 64,
}


def _record(
    outcome: dict[str, Any], *, digest: str = "sha256:" + "0" * 64
) -> dict[str, Any]:
    return {
        "record_id": "decision:" + digest[-8:],
        "record_digest": digest,
        "outcome": outcome,
    }


def acted(option_id: str, **kw: Any) -> dict[str, Any]:
    return {"records": [_record({"outcome": "acted", "option_id": option_id}, **kw)]}


def abstained(reason: str = "insufficient_confidence", **kw: Any) -> dict[str, Any]:
    outcome = {"outcome": "abstained", "reasons": [{"reason": reason}]}
    return {"records": [_record(outcome, **kw)]}


@dataclass
class FakeTransport:
    """Answers every ``decide`` with ``answer``; records every request and op."""

    answer: Any = None
    fail: BaseException | None = None
    requests: list[Mapping[str, Any]] = field(default_factory=list)
    ops: list[Mapping[str, Any]] = field(default_factory=list)

    async def decide(self, request: Mapping[str, Any]) -> Any:
        self.requests.append(request)
        if self.fail is not None:
            raise self.fail
        return self.answer

    async def log(self, op: Mapping[str, Any]) -> Any:
        self.ops.append(op)
        return {"record_id": "logged"}

    def run(self, call: Any) -> Any:
        return asyncio.run(call)

    def op_names(self) -> list[str]:
        return [str(op["op"]) for op in self.ops]


def _runner(
    transport: FakeTransport, *, bound: bool = True
) -> EpistemicGraphDecisionRunner:
    bindings = StaticBindings(
        {
            "au.connector.tool": Binding(
                feature_schema=_SCHEMA, policy={"policy": "default"}
            )
        }
        if bound
        else {}
    )
    return EpistemicGraphDecisionRunner(
        transport=transport, tenant="tenant-t", bindings=bindings
    )


def test_an_unbound_point_never_calls_eg_and_falls_back() -> None:
    transport = FakeTransport(answer=acted("search"))
    choice = _runner(transport, bound=False).choose(
        "au.connector.tool", OPTIONS, lambda: "get"
    )
    assert (choice.option_id, choice.decided, choice.reason) == (
        "get",
        False,
        "unbound",
    )
    assert transport.requests == []
    assert transport.ops == []


def test_a_decision_is_made_and_recorded() -> None:
    transport = FakeTransport(answer=acted("search"))
    choice = _runner(transport).choose("au.connector.tool", OPTIONS, lambda: "get")
    assert (choice.option_id, choice.decided, choice.reason) == (
        "search",
        True,
        "acted",
    )
    assert transport.op_names() == ["commit"]
    request = transport.requests[0]
    assert request["question"] == {
        "question_id": "au.connector.tool",
        "kind": "route",
        "safety": "ordinary",
    }
    assert request["tenant_id"] == "tenant-t"
    ids = [o["option_id"] for o in request["candidates"]["options"]]
    assert ids == ["get", "search"], "declared options are sorted"


def test_an_abstention_falls_back() -> None:
    transport = FakeTransport(answer=abstained())
    choice = _runner(transport).choose("au.connector.tool", OPTIONS, lambda: "get")
    assert (choice.option_id, choice.decided) == ("get", False)
    assert choice.reason == "abstained: insufficient_confidence"
    assert transport.op_names() == ["commit"], "an abstained record is still durable"


def test_a_transport_failure_falls_back_with_a_named_reason() -> None:
    transport = FakeTransport(fail=ConnectionError("engine down"))
    choice = _runner(transport).choose("au.connector.tool", OPTIONS, lambda: "get")
    assert choice.option_id == "get"
    assert not choice.decided
    assert choice.reason.startswith("unavailable: ConnectionError: engine down")
    assert transport.ops == [], "nothing to log: EG never answered"


def test_an_option_eg_was_not_offered_is_never_obeyed() -> None:
    transport = FakeTransport(answer=acted("delete-everything"))
    choice = _runner(transport).choose("au.connector.tool", OPTIONS, lambda: "get")
    assert (choice.option_id, choice.decided) == ("get", False)
    assert choice.reason == "foreign_option: delete-everything"


def test_the_writeback_point_always_logs_never_only_samples() -> None:
    transport = FakeTransport(answer=abstained())
    bindings = StaticBindings(
        {"au.connector.writeback": Binding(feature_schema=_SCHEMA, policy={})}
    )
    runner = EpistemicGraphDecisionRunner(
        transport=transport, tenant="tenant-t", bindings=bindings
    )
    runner.choose("au.connector.writeback", [Option("no_write")], lambda: "no_write")
    assert transport.requests[0]["question"]["safety"] == "write_back"
    assert transport.op_names() == ["commit"]


async def test_the_async_path_shares_the_contract() -> None:
    transport = FakeTransport(answer=acted("search"))
    choice = await _runner(transport).achoose(
        "au.connector.tool", OPTIONS, lambda: "get"
    )
    assert (choice.option_id, choice.decided) == ("search", True)
    assert transport.op_names() == ["commit"]


def test_a_sync_transport_without_an_engine_loop_falls_back_instead_of_blocking() -> (
    None
):
    transport = GeneratedTransport(client=object())

    async def never() -> None:
        raise AssertionError("must not run")

    with pytest.raises(DecideUnavailable):
        transport.run(never())
    loop = asyncio.new_event_loop()
    loop.close()
    with pytest.raises(DecideUnavailable):
        GeneratedTransport(client=object(), loop=loop).run(never())


def test_generated_sender_lookup_is_dynamic_and_costs_only_unavailable() -> None:
    """The mechanism, not a snapshot of what EG happens to publish today."""
    with pytest.raises(DecideUnavailable, match="absent"):
        _generated("no_such_generated_module", "whatever")
    with pytest.raises(DecideUnavailable, match="does not yet generate"):
        _generated("query", "no_such_sender_either")
    # A version of EG that has not yet published a given sender (Decide's
    # send_decide included) would raise the same DecideUnavailable here,
    # never at import time of this module.
    assert _generated("query", _A_SENDER_ALWAYS_PUBLISHED) is not None


async def test_generated_transport_calls_egs_real_send_decide() -> None:
    """Proves the wire request this runner builds reaches EG's own generated
    ``send_decide`` wrapper without raising -- not a hand-rolled fake of it.
    """

    @dataclass
    class _MockClient:
        calls: list[tuple[str, Any, Any]] = field(default_factory=list)

        async def _send(
            self, method: str, params: Any, graph: Any, *, idempotency_key: Any = None
        ) -> Any:
            self.calls.append((method, params, graph))
            return acted("search")

    client = _MockClient()
    transport = GeneratedTransport(client=client)
    request: dict[str, Any] = {
        "tenant_id": "tenant-t",
        "question": {
            "question_id": "au.connector.tool",
            "kind": "route",
            "safety": "ordinary",
        },
        "candidates": {"source": "declared", "options": []},
        "feature_schema": _SCHEMA,
        "head": None,
        "policy": {"policy": "default"},
        "params": [],
        "max_records": 1,
    }
    result = await transport.decide(request)
    assert result == acted("search")
    method, params, _graph = client.calls[0]
    assert method == "Decide"
    assert params == {"request": request}


def test_read_batch_reads_an_executed_offered_option() -> None:
    reading = read_batch(acted("search"), frozenset({"search", "get"}))
    assert reading == Reading("search", "acted", reading.record, {})


def test_read_batch_reads_an_abstention() -> None:
    reading = read_batch(abstained("insufficient_confidence"), frozenset({"search"}))
    assert reading.option_id is None
    assert reading.reason == "abstained: insufficient_confidence"


def test_read_batch_rejects_an_option_never_offered() -> None:
    reading = read_batch(acted("delete-everything"), frozenset({"search", "get"}))
    assert reading == Reading(
        None, "foreign_option: delete-everything", reading.record, {}
    )


def test_read_batch_reports_an_empty_batch_as_unavailable() -> None:
    assert read_batch({"records": []}, frozenset({"search"})) == Reading(
        None, "unavailable: empty decision batch", None, {}
    )


def test_request_for_binds_tenant_question_and_declared_candidates() -> None:
    binding = Binding(feature_schema=_SCHEMA, policy={"policy": "default"})
    request = request_for(
        CONNECTOR_TOOL,
        binding,
        tenant="tenant-t",
        candidates={"source": "declared", "options": []},
    )
    assert request["tenant_id"] == "tenant-t"
    assert request["question"] == {
        "question_id": "au.connector.tool",
        "kind": "route",
        "safety": "ordinary",
    }
    assert request["feature_schema"] == _SCHEMA
    assert request["head"] is None
    assert request["max_records"] == 1


def test_sampled_keeps_a_reproducible_fraction_by_record_digest() -> None:
    kept = _record({"outcome": "abstained", "reasons": []}, digest="sha256:" + "0" * 64)
    skipped = _record(
        {"outcome": "abstained", "reasons": []}, digest="sha256:" + "0" * 63 + "1"
    )
    assert sampled(CONNECTOR_TOOL, kept) is True
    assert sampled(CONNECTOR_TOOL, skipped) is False


def test_points_registry_and_bindings() -> None:
    assert POINTS["au.connector.tool"] is CONNECTOR_TOOL
    assert point("au.connector.writeback") is CONNECTOR_WRITEBACK
    assert CONNECTOR_TOOL.log_mode is LogMode.SAMPLED
    assert CONNECTOR_WRITEBACK.log_mode is LogMode.ALWAYS
    assert CONNECTOR_TOOL.schema_component_id == "decide.schema.au.connector.tool"
    assert EMPTY_BINDINGS.binding_for(CONNECTOR_TOOL) is None

    custom: DecisionPoint = DecisionPoint("x.y", "route")
    bindings: Bindings = StaticBindings({"x.y": Binding(feature_schema={}, policy={})})
    assert bindings.binding_for(custom) is not None
    assert bindings.binding_for(CONNECTOR_TOOL) is None


def test_decide_transport_protocol_and_default_timeout() -> None:
    transport: DecideTransport = GeneratedTransport(client=object())
    assert isinstance(transport, GeneratedTransport)
    assert transport.sync_timeout_s == DEFAULT_SYNC_TIMEOUT_S
