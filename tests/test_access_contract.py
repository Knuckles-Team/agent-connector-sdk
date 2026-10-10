"""Access-contract parsing and refusal (SDK-CONNECTOR-CONTROL-R021, CC-11)."""

from __future__ import annotations

import pytest

from agent_connector_sdk.access_contract import (
    AC,
    ACCESS_KINDS,
    PAGINATION_MODES,
    PUSHDOWN_OPS,
    AccessContract,
    AccessContractError,
    access_contract_vocabulary,
    parse_access_contracts,
)

_HEAD = """
@prefix ac: <https://knuckles-team.github.io/agent-connector-sdk/access#> .
@prefix ex: <https://example.invalid/fake#> .
"""

_FAKE = (
    _HEAD
    + """
# A fake connector: one class answered by an MCP tool.
ex:Ticket a <http://www.w3.org/2002/07/owl#Class> .

ex:ticketAccess a ac:AccessContract ;
    ac:classIri ex:Ticket ;
    ac:sourceId "fake-tracker" ;
    ac:entity "ticket" ;
    ac:keyField "id" ;
    ac:accessKind "mcp_tool" ;
    ac:operation "fake_ticket_query" ;
    ac:parameter "status", "cursor" ;
    ac:pagination "cursor" ;
    ac:pushdown "filter", "limit" ;
    ac:authRef "env://FAKE_TRACKER_TOKEN" ;
    ac:rateLimitPerMinute 120 ;
    ac:freshnessSeconds 60 ;
    ac:costHint "low" .

ex:titleBinding a ac:PropertyBinding ;
    ac:contract ex:ticketAccess ; ac:property ex:title ; ac:field "summary" .
"""
)


def _variant(old: str, new: str) -> str:
    assert old in _FAKE
    return _FAKE.replace(old, new)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R021")
def test_parses_typed_contract_from_fake_connector() -> None:
    (contract,) = parse_access_contracts(_FAKE)
    assert isinstance(contract, AccessContract)
    assert contract.access_kind in ACCESS_KINDS
    assert contract.pagination in PAGINATION_MODES
    assert contract.pushdown <= PUSHDOWN_OPS
    ex = "https://example.invalid/fake#"
    assert contract.class_iri == ex + "Ticket"
    assert contract.access_kind == "mcp_tool"
    assert contract.operation == "fake_ticket_query"
    assert contract.parameters == ("cursor", "status")
    assert contract.pushdown == frozenset({"filter", "limit"})
    assert contract.auth_ref == "env://FAKE_TRACKER_TOKEN"
    assert (contract.rate_limit_per_minute, contract.freshness_seconds) == (120, 60)
    assert contract.virtual_mapping_fields() == {
        "mapping_id": ex + "ticketAccess",
        "source_id": "fake-tracker",
        "entity": "ticket",
        "class_iri": ex + "Ticket",
        "key_field": "id",
        "predicates": ((ex + "title", "summary"),),
    }


def test_optional_hints_default_to_unknown() -> None:
    text = _variant('    ac:costHint "low" .', '    ac:keyField2 "x" .')
    text = text.replace("    ac:rateLimitPerMinute 120 ;\n", "")
    (contract,) = parse_access_contracts(text)
    assert contract.cost_hint == "unknown"
    assert contract.rate_limit_per_minute is None


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('"env://FAKE_TRACKER_TOKEN"', '"sk-live-123456"', "not a secret"),
        ('"filter", "limit"', '"filter", "join"', "unknown ac:pushdown"),
        ('    ac:operation "fake_ticket_query" ;\n', "", "missing ac:operation"),
        ('"mcp_tool"', '"carrier_pigeon"', "unknown ac:accessKind"),
        (
            '"cursor" ;\n    ac:pushdown',
            '"scroll" ;\n    ac:pushdown',
            "unknown ac:pagination",
        ),
        (
            "ac:freshnessSeconds 60",
            'ac:freshnessSeconds "soon"',
            "non-negative integer",
        ),
    ],
)
def test_refuses_invalid_contract(old: str, new: str, message: str) -> None:
    with pytest.raises(AccessContractError, match=message) as info:
        parse_access_contracts(_variant(old, new))
    assert "sk-live" not in str(info.value)


def test_refuses_undeclared_prefix_and_blank_nodes() -> None:
    with pytest.raises(AccessContractError, match="undeclared prefix"):
        parse_access_contracts("zz:a zz:b zz:c .")
    with pytest.raises(AccessContractError, match="unsupported Turtle"):
        parse_access_contracts(_HEAD + "ex:a ex:b [ ex:c 1 ] .")


def test_packaged_vocabulary_parses_and_declares_terms() -> None:
    vocabulary = access_contract_vocabulary()
    assert parse_access_contracts(vocabulary) == ()
    for term in ("AccessContract", "pushdown", "authRef", "keyField"):
        assert f"ac:{term} a owl:" in vocabulary
    assert AC.endswith("access#")
