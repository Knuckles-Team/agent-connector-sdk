"""SDK-CONNECTOR-CONTROL-R022: pack-scoped owl:imports."""

from __future__ import annotations

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import OWL

from agent_connector_sdk.artifacts.ontology_imports import (
    IMPORT_REQUIREMENT_PREFIX,
    scope_ontology_imports,
)
from agent_connector_sdk.contracts import CapturedArtifact, ServerIdentity

HUB = "http://knuckles.team/kg"
SELF = "ontology://demo/demo.ttl"
SIBLING = "ontology://demo/extra.ttl"
PACK = frozenset({SELF, SIBLING})


def _entry(body: str, media_type: str = "text/turtle") -> CapturedArtifact:
    return CapturedArtifact(
        kind="resource",
        uri=SELF,
        name="demo",
        media_type=media_type,
        body=body,
        server=ServerIdentity(name="demo", version="1.0.0"),
    )


def _requirements(entry: CapturedArtifact) -> list[str]:
    return list(entry.annotations.requires_capabilities)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R022")
def test_external_import_is_removed_and_recorded() -> None:
    body = (
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "<http://x/demo> a owl:Ontology ;\n"
        f"    owl:imports <{HUB}> ;\n"
        '    owl:versionInfo "1" .\n'
    )
    scoped = scope_ontology_imports(_entry(body), PACK)
    assert HUB not in scoped.body
    assert "owl:versionInfo" in scoped.body
    assert "a owl:Ontology" in scoped.body
    assert _requirements(scoped) == [f"{IMPORT_REQUIREMENT_PREFIX}{HUB}"]


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R022")
def test_comment_import_example_is_not_recorded_as_a_capability() -> None:
    body = (
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "# Example owl:imports <urn:phantom>; documentation only.\n"
        "<urn:main> a owl:Ontology ; owl:imports <urn:actual> .\n"
    )
    scoped = scope_ontology_imports(_entry(body), PACK)
    assert (
        scoped.body == "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "# Example owl:imports <urn:phantom>; documentation only.\n"
        "<urn:main> a owl:Ontology .\n"
    )
    assert _requirements(scoped) == [f"{IMPORT_REQUIREMENT_PREFIX}urn:actual"]


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R022")
def test_commented_legal_import_separator_preserves_documentation() -> None:
    body = (
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "<http://knuckles.team/kg/legal-compliance-demo> a owl:Ontology ;\n"
        "# <name> that owl:imports <http://knuckles.team/kg/legal-compliance>; "
        "(2) declare one\n"
        "    owl:imports <http://knuckles.team/kg/legal> .\n"
    )
    scoped = scope_ontology_imports(_entry(body), PACK)
    assert (
        "# <name> that owl:imports <http://knuckles.team/kg/legal-compliance>; "
        "(2) declare one\n"
    ) in scoped.body
    assert "http://knuckles.team/kg/legal-compliance" not in _requirements(scoped)
    assert _requirements(scoped) == [
        f"{IMPORT_REQUIREMENT_PREFIX}http://knuckles.team/kg/legal"
    ]
    assert "owl:imports <http://knuckles.team/kg/legal>" not in scoped.body


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R022")
def test_import_text_in_literals_does_not_change_graph_or_bytes() -> None:
    body = (
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "<urn:main#subject> a owl:Ontology ;\n"
        '    rdfs:comment "docs owl:imports <urn:phantom>; only" ;\n'
        '    rdfs:label """more docs owl:imports <urn:phantom>;\n'
        '    with a second line""" ;\n'
        "    owl:imports <urn:actual> .\n"
    )
    scoped = scope_ontology_imports(_entry(body), PACK)
    assert "owl:imports <urn:phantom>" in scoped.body
    assert "ontology-import:urn:phantom" not in _requirements(scoped)
    assert _requirements(scoped) == [f"{IMPORT_REQUIREMENT_PREFIX}urn:actual"]

    before = Graph().parse(data=body, format="turtle")
    after = Graph().parse(data=scoped.body, format="turtle")
    assert set(before) - set(after) == {
        (URIRef("urn:main#subject"), OWL.imports, URIRef("urn:actual"))
    }
    assert set(after) - set(before) == set()


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R022")
def test_trailing_import_and_mixed_list() -> None:
    body = (
        "<http://x/demo> a owl:Ontology ;\n"
        f"    owl:imports <{HUB}>, <{SIBLING}>, <{HUB}/enterprise> .\n"
        "<http://x/demo#A> a owl:Class ;\n"
        f"    owl:imports <{HUB}/legal-compliance> .\n"
    )
    scoped = scope_ontology_imports(_entry(body), PACK)
    assert f"owl:imports <{SIBLING}> ." in scoped.body
    assert "<http://x/demo#A> a owl:Class .\n" in scoped.body
    assert "knuckles.team" not in scoped.body
    assert _requirements(scoped) == [
        f"{IMPORT_REQUIREMENT_PREFIX}{HUB}",
        f"{IMPORT_REQUIREMENT_PREFIX}{HUB}/enterprise",
        f"{IMPORT_REQUIREMENT_PREFIX}{HUB}/legal-compliance",
    ]


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R022")
def test_adjacent_trailing_drops_keep_first_import_and_comments() -> None:
    body = (
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "<urn:demo> a owl:Ontology ;\n"
        f"    owl:imports <{SIBLING}>, # keep A\n"
        "        <urn:drop-b>, # drop B\n"
        "        <urn:drop-c> .\n"
    )

    scoped = scope_ontology_imports(_entry(body), PACK)

    assert "# keep A\n" in scoped.body
    assert "# drop B\n" in scoped.body
    assert "<urn:drop-b>" not in scoped.body
    assert "<urn:drop-c>" not in scoped.body
    assert _requirements(scoped) == [
        f"{IMPORT_REQUIREMENT_PREFIX}urn:drop-b",
        f"{IMPORT_REQUIREMENT_PREFIX}urn:drop-c",
    ]

    before = Graph().parse(data=body, format="turtle")
    after = Graph().parse(data=scoped.body, format="turtle")
    assert {
        value
        for subject, predicate, value in after
        if subject == URIRef("urn:demo") and predicate == OWL.imports
    } == {URIRef(SIBLING)}
    assert set(before) - set(after) == {
        (URIRef("urn:demo"), OWL.imports, URIRef("urn:drop-b")),
        (URIRef("urn:demo"), OWL.imports, URIRef("urn:drop-c")),
    }
    assert set(after) - set(before) == set()


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R022")
def test_lone_statement_and_full_iri_predicate() -> None:
    body = (
        "<http://x/demo> a owl:Ontology .\n"
        f"<http://x/demo> <http://www.w3.org/2002/07/owl#imports> <{HUB}> .\n"
        "<http://x/demo#B> a owl:Class .\n"
    )
    scoped = scope_ontology_imports(_entry(body), PACK)
    assert (
        scoped.body
        == "<http://x/demo> a owl:Ontology .\n<http://x/demo#B> a owl:Class .\n"
    )


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R022")
def test_self_import_is_removed() -> None:
    body = f"<http://x/demo> a owl:Ontology ;\n    owl:imports <{SELF}> .\n"
    scoped = scope_ontology_imports(_entry(body), PACK)
    assert scoped.body == "<http://x/demo> a owl:Ontology .\n"


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R022")
def test_in_pack_imports_keep_bytes_and_identity() -> None:
    entry = _entry(f"<http://x/demo> a owl:Ontology ;\n    owl:imports <{SIBLING}> .\n")
    assert scope_ontology_imports(entry, PACK) is entry


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R022")
def test_rdfxml_import_is_removed() -> None:
    body = (
        '<owl:Ontology rdf:about="http://x/demo">\n'
        f'  <owl:imports rdf:resource="{HUB}"/>\n'
        f'  <owl:imports rdf:resource="{SIBLING}"/>\n'
        "</owl:Ontology>\n"
    )
    scoped = scope_ontology_imports(_entry(body, "application/rdf+xml"), PACK)
    assert HUB not in scoped.body
    assert SIBLING in scoped.body
    assert _requirements(scoped) == [f"{IMPORT_REQUIREMENT_PREFIX}{HUB}"]


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R022")
def test_scoping_is_deterministic() -> None:
    body = f"<http://x/demo> a owl:Ontology ;\n    owl:imports <{HUB}> .\n"
    first = scope_ontology_imports(_entry(body), PACK)
    second = scope_ontology_imports(_entry(body), PACK)
    assert first == second
