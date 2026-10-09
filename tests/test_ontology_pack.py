"""Connector manifest to ontology pack compilation (AU-BOUNDARY-R030)."""

from __future__ import annotations

from agent_connector_sdk.manifest.model import (
    ConnectorManifest,
    IntegrityInfo,
    ProvenanceSpec,
    ResourceRelation,
    ResourceSpec,
    SchemaMapping,
)
from agent_connector_sdk.manifest.ontology_pack import (
    OntologyClassSpec,
    OntologyDatatypePropertySpec,
    OntologyObjectPropertySpec,
    OntologySpec,
    compile_manifest_ontology,
    compile_manifest_ontology_spec,
)


def _manifest() -> ConnectorManifest:
    return ConnectorManifest(
        connector="widgetworks",
        resources=[
            ResourceSpec(
                name="WidgetOrder",
                label="Widget Order",
                id_prefix="order",
                relations=[
                    ResourceRelation(name="placedBy", target="Customer"),
                ],
            ),
            ResourceSpec(name="Customer"),
        ],
        schema_mappings={
            "WidgetOrder": SchemaMapping(
                ontology_class="BaseOrder", fields={"status": "xsd:string"}
            ),
        },
        provenance=ProvenanceSpec(integrity=IntegrityInfo(hash="0" * 64)),
    )


def test_ontology_spec_dataclasses_construct_directly() -> None:
    spec = OntologySpec(
        classes=[
            OntologyClassSpec(
                local="Widget", label="Widget", parent=None, id_prefix="widget"
            )
        ],
        object_properties=[
            OntologyObjectPropertySpec(
                local="owns",
                label="Owns",
                domain="Widget",
                range="Customer",
                lpg_rel_type="OWNS",
            )
        ],
        datatype_properties=[
            OntologyDatatypePropertySpec(
                local="status", label="Status", range="xsd:string"
            )
        ],
    )

    assert spec.classes[0].local == "Widget"
    assert spec.object_properties[0].lpg_rel_type == "OWNS"
    assert spec.datatype_properties[0].range == "xsd:string"


def test_compile_manifest_ontology_spec_projects_classes_properties_and_maps() -> None:
    spec = compile_manifest_ontology_spec(_manifest())
    assert isinstance(spec, OntologySpec)

    classes_by_local = {c.local: c for c in spec.classes}
    assert isinstance(classes_by_local["WidgetOrder"], OntologyClassSpec)
    assert classes_by_local["WidgetOrder"].label == "Widget Order"
    assert classes_by_local["WidgetOrder"].parent == "BaseOrder"
    assert classes_by_local["Customer"].label == "Customer"
    assert classes_by_local["Customer"].parent is None

    assert spec.type_map["WidgetOrder"] == ("WidgetOrder", "order")
    assert spec.type_map["Customer"] == ("Customer", "customer")

    (rel,) = spec.object_properties
    assert rel.local == "placedBy"
    assert rel.domain == "WidgetOrder"
    assert rel.range == "Customer"
    assert rel.lpg_rel_type == "PLACED_BY"
    assert spec.relation_map["placedBy"] == ("PLACED_BY", "Customer")

    (dtp,) = spec.datatype_properties
    assert dtp.local == "status"
    assert dtp.range == "xsd:string"


def test_compile_manifest_ontology_is_deterministic_turtle() -> None:
    ttl_first = compile_manifest_ontology(_manifest())
    ttl_second = compile_manifest_ontology(_manifest())

    assert ttl_first == ttl_second
    assert ":WidgetOrder a owl:Class" in ttl_first
    assert "rdfs:subClassOf :BaseOrder" in ttl_first
    assert ":placedBy a owl:ObjectProperty" in ttl_first
    assert "rdfs:range :Customer" in ttl_first
    assert ":status a owl:DatatypeProperty" in ttl_first
    assert "widgetworks Ontology (generated)" in ttl_first


def test_compile_manifest_ontology_uses_resolved_ontology_source() -> None:
    manifest = _manifest().model_copy(update={"ontology_source": "widgets"})

    ttl = compile_manifest_ontology(manifest)

    assert "<http://knuckles.team/kg/widgets>" in ttl
    assert "widgetworks" not in ttl
