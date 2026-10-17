"""SDK-CONNECTOR-CONTROL-R014.23: typed epistemic-graph compute adapter."""

from __future__ import annotations

from typing import Any

import pytest

from agent_connector_sdk.compute import (
    COMPUTE_SCOPES,
    AlgorithmBinding,
    ComputeUnavailableError,
    EngineCompute,
    MethodNotServedError,
    connect_compute,
)
from agent_connector_sdk.ingest.engine import EngineSettings

pytestmark = pytest.mark.spec("SDK-CONNECTOR-CONTROL-R014.23")

VOCAB = "http://knuckles.team/kg/quant#"
ANALYSIS = "http://knuckles.team/kg/quant#SignalFusionAnalysis"


class _NotServed(Exception):
    code = "METHOD_NOT_YET_SERVED"


class _Finance:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def signal_models(self, **params: Any) -> dict[str, Any]:
        self.calls.append(params)
        return {"posterior_up": 0.7}

    def unserved(self, **params: Any) -> None:
        raise _NotServed("declared but not served")


class _Rdf:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.queries: list[str] = []

    def sparql(self, *, query: str) -> list[dict[str, Any]]:
        self.queries.append(query)
        return self.rows


class _Client:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.finance = _Finance()
        self.rdf = _Rdf(rows or [])


def test_ontology_selects_the_algorithm_and_the_engine_runs_it():
    client = _Client(
        [
            {
                "algorithm": VOCAB + "BayesianSignalFusion",
                "method": "finance.signal_models",
                "op": "bayes_fuse",
            }
        ]
    )
    compute = EngineCompute(client)

    result = compute.analyse(ANALYSIS, vocabulary=VOCAB, request={"directions": {}})

    assert result == {"posterior_up": 0.7}
    assert client.finance.calls == [{"op": "bayes_fuse", "request": {"directions": {}}}]
    query = client.rdf.queries[0]
    assert f"<{ANALYSIS}> <{VOCAB}appliesAlgorithm> ?algorithm" in query
    assert f"<{VOCAB}servedBy> ?method" in query


def test_unbound_analysis_is_refused_not_computed_locally():
    compute = EngineCompute(_Client([]))
    with pytest.raises(MethodNotServedError) as caught:
        compute.select_algorithms(ANALYSIS, vocabulary=VOCAB)
    assert caught.value.method == ANALYSIS


def test_missing_and_unserved_methods_raise_typed_refusal():
    compute = EngineCompute(_Client())
    with pytest.raises(MethodNotServedError):
        compute.call("finance.no_such_method")
    with pytest.raises(MethodNotServedError):
        compute.call("finance.unserved")
    with pytest.raises(MethodNotServedError):
        compute.run(AlgorithmBinding("urn:x", "nowhere.method"))


@pytest.mark.parametrize(
    ("analysis", "vocabulary", "method"),
    [
        ("not an iri", VOCAB, "finance.signal_models"),
        (ANALYSIS, "http://x/no-separator", "finance.signal_models"),
        (ANALYSIS + "> . ?s ?p ?o", VOCAB, "finance.signal_models"),
    ],
)
def test_selection_inputs_are_validated(analysis, vocabulary, method):
    with pytest.raises(ValueError):
        EngineCompute(_Client()).select_algorithms(analysis, vocabulary=vocabulary)


def test_bad_client_path_rejected():
    with pytest.raises(ValueError):
        EngineCompute(_Client()).call("__class__")


def test_connect_without_endpoint_is_unavailable(monkeypatch):
    monkeypatch.delenv("EPISTEMIC_GRAPH_ENDPOINT", raising=False)
    with pytest.raises(ComputeUnavailableError):
        connect_compute()


def test_compute_session_asks_for_compute_scopes_only():
    settings = EngineSettings(
        endpoint="unix:///run/eg.sock", auth_secret_ref="env://X", tenant="t", graph="g"
    )
    claims = settings.verified_context(COMPUTE_SCOPES)
    assert claims["scopes"] == ["compute:finance", "sparql:read"]
    assert settings.verified_context()["scopes"] == ["source:ingest", "blob:write"]
