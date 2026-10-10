"""SDK-CONNECTOR-CONTROL-R022: pack-scoped owl:imports."""

from __future__ import annotations

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


def test_self_import_is_removed() -> None:
    body = f"<http://x/demo> a owl:Ontology ;\n    owl:imports <{SELF}> .\n"
    scoped = scope_ontology_imports(_entry(body), PACK)
    assert scoped.body == "<http://x/demo> a owl:Ontology .\n"


def test_in_pack_imports_keep_bytes_and_identity() -> None:
    entry = _entry(f"<http://x/demo> a owl:Ontology ;\n    owl:imports <{SIBLING}> .\n")
    assert scope_ontology_imports(entry, PACK) is entry


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


def test_scoping_is_deterministic() -> None:
    body = f"<http://x/demo> a owl:Ontology ;\n    owl:imports <{HUB}> .\n"
    first = scope_ontology_imports(_entry(body), PACK)
    second = scope_ontology_imports(_entry(body), PACK)
    assert first == second
