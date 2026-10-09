"""Apache Egeria open-metadata vendor extractor (SDK-SOURCE-INGEST-R006.30).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.egeria``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
Egeria's open-metadata/glossary/governance/lineage records map to the
canonical ArchiMate concepts so Egeria data reconciles with the
ServiceNow/ERPNext/Camunda/infra crosswalk by GUID:

    asset (DataStore/Database/FileFolder) -> ``DataConnector``  egeria_asset:{guid}
    asset (DataSet/Table/DataFile)        -> ``DataObject``     egeria_asset:{guid}  (PART_OF store)
    glossary term                         -> ``Concept``        egeria_term:{guid}
    glossary category                     -> ``GlossaryCategory`` egeria_category:{guid}
    governance policy / rule              -> ``Policy``         egeria_policy:{guid}
    governance principle                  -> ``Principle``      egeria_policy:{guid}
    governance strategy / imperative      -> ``Goal``           egeria_policy:{guid}
    software server / host                -> ``Server``         egeria_server:{guid}
    connection                            -> ``DataConnector``  egeria_connection:{guid}
    lineage process                       -> ``ProcessModel``   egeria_process:{guid}

Lineage ``DataFlow`` records become ``flowsTo``/``derivesFrom`` relationships
-- the unique payload Egeria contributes that the KG does not model natively.
Every entity carries ``externalToolId`` (the Egeria GUID) and
``domain="egeria"``. The client is injected (duck-typed) via
``config["client"]``; this module performs no network calls itself.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "egeria"

_STORE_HINTS = ("datastore", "database", "filefolder", "filesystem", "datasource")
_OBJECT_HINTS = ("dataset", "datafile", "table", "relationaltable", "datafield")

_KG_TYPES = {
    "SoftwareServer": "Server",
    "DeployedSoftwareComponent": "Tool",
    "RelationalDatabase": "DataObject",
    "DeployedDatabaseSchema": "DataObject",
    "Process": "ProcessModel",
    "Collection": "Concept",
}
_STRUCTURAL = {
    "hosts",
    "realizes",
    "secures",
    "same-as",
    "means",
    "deploys",
    "monitors",
    "reads",
    "groups",
}


def _get(record: Any, key: str, default: Any = None) -> Any:
    """Tolerant field access for dict records (or attr-style objects)."""
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _first(record: Any, *keys: str) -> Any:
    """Return the first present, non-empty value among ``keys``."""
    for key in keys:
        value = _get(record, key)
        if value is not None and value != "":
            return value
    return None


def _call(client: Any, name: str) -> list[Any]:
    """Call a client list-method if present, returning a list (tolerant)."""
    method = getattr(client, name, None)
    if not callable(method):
        return []
    try:
        result = method()
    except TypeError:
        try:
            result = method({})
        except Exception:
            return []
    except Exception:
        return []
    if isinstance(result, dict):
        result = (
            result.get("items") or result.get("results") or result.get("elements") or []
        )
    return list(result) if result else []


def _classification_props(record: Any) -> dict[str, Any]:
    """Lift Egeria classifications into flat entity properties."""
    properties: dict[str, Any] = {}
    confidentiality = _first(record, "confidentiality", "confidentialityLevel")
    if confidentiality is not None:
        properties["confidentialityLevel"] = confidentiality
    retention = _first(record, "retention", "retentionPeriod")
    if retention is not None:
        properties["retentionPeriod"] = retention
    return properties


def _asset_type(record: Any) -> tuple[str, str]:
    """Resolve an Egeria asset record to (KG node type, role: store|object|other)."""
    type_name = str(_first(record, "typeName", "type", "category") or "").lower()
    if any(hint in type_name for hint in _OBJECT_HINTS):
        return "DataObject", "object"
    if any(hint in type_name for hint in _STORE_HINTS):
        return "DataConnector", "store"
    return "EAFactSheet", "other"


def _gov_type(record: Any) -> str:
    """Map an Egeria governance-definition typeName to a KG class."""
    type_name = str(_first(record, "typeName", "type") or "").lower()
    if "principle" in type_name:
        return "Principle"
    if "strategy" in type_name or "imperative" in type_name:
        return "Goal"
    return "Policy"


def _kg_type(type_name: Any) -> str:
    return _KG_TYPES.get(str(type_name or ""), "DataConnector")


def _flow_rel(label: Any) -> str:
    """Map a reconciliation/lineage edge label to a KG relationship type."""
    return "dependsOn" if str(label or "").lower() in _STRUCTURAL else "flowsTo"


def _as_list(value: Any) -> list[Any]:
    """Coerce a scalar/None/list relation field into a clean list."""
    if value is None or value == "":
        return []
    if isinstance(value, list | tuple | set):
        return [item for item in value if item]
    return [value]


def extract(config: Any) -> ChangeSet:
    """Extract Egeria open-metadata artifacts into a uniform ``ChangeSet``."""
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    entities: list[Entity] = []
    relationships: list[Relationship] = []
    seen: set[str] = set()

    def _base_props(record: Any) -> dict[str, Any]:
        return {
            "domain": "egeria",
            "externalToolId": _first(record, "guid", "GUID", "id"),
            "qualifiedName": _first(record, "qualifiedName", "qualified_name"),
        }

    def _add(node_id: str, node_type: str, properties: dict[str, Any]) -> bool:
        if node_id in seen:
            return False
        seen.add(node_id)
        entities.append(Entity(id=node_id, node_type=node_type, properties=properties))
        return True

    for record in _call(client, "list_assets"):
        guid = _first(record, "guid", "GUID", "id")
        if not guid:
            continue
        node_id = f"egeria_asset:{guid}"
        node_type, role = _asset_type(record)
        properties = {
            **_base_props(record),
            "name": _first(record, "displayName", "name", "qualifiedName"),
            **_classification_props(record),
        }
        _add(node_id, node_type, properties)
        host = _first(record, "hostGuid", "serverGuid", "hostedOnGuid")
        if role == "store" and host:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"egeria_server:{host}",
                    relationship="HOSTED_ON",
                )
            )
        parent = _first(record, "storeGuid", "parentGuid", "assetGuid")
        if role == "object" and parent:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"egeria_asset:{parent}",
                    relationship="PART_OF",
                )
            )
        for policy in _as_list(_first(record, "governedByGuids", "policyGuids")):
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"egeria_policy:{policy}",
                    relationship="governedBy",
                )
            )

    for record in _call(client, "list_glossary_categories"):
        guid = _first(record, "guid", "GUID", "id")
        if not guid:
            continue
        node_id = f"egeria_category:{guid}"
        _add(
            node_id,
            "GlossaryCategory",
            {**_base_props(record), "name": _first(record, "displayName", "name")},
        )
        parent = _first(record, "parentCategoryGuid", "parentGuid")
        if parent:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"egeria_category:{parent}",
                    relationship="PART_OF",
                )
            )

    for record in _call(client, "list_glossary_terms"):
        guid = _first(record, "guid", "GUID", "id")
        if not guid:
            continue
        node_id = f"egeria_term:{guid}"
        _add(
            node_id,
            "Concept",
            {
                **_base_props(record),
                "name": _first(record, "displayName", "name"),
                "summary": _first(record, "summary", "description"),
            },
        )
        category = _first(record, "categoryGuid", "category")
        if category:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"egeria_category:{category}",
                    relationship="IN_CATEGORY",
                )
            )

    for record in _call(client, "list_governance_definitions"):
        guid = _first(record, "guid", "GUID", "id")
        if not guid:
            continue
        _add(
            f"egeria_policy:{guid}",
            _gov_type(record),
            {
                **_base_props(record),
                "name": _first(record, "title", "displayName", "name"),
                "governanceDomain": _first(record, "domain", "domainIdentifier"),
            },
        )

    for record in _call(client, "list_software_servers"):
        guid = _first(record, "guid", "GUID", "id")
        if not guid:
            continue
        _add(
            f"egeria_server:{guid}",
            "Server",
            {
                **_base_props(record),
                "name": _first(record, "displayName", "name", "hostName"),
            },
        )

    for record in _call(client, "list_connections"):
        guid = _first(record, "guid", "GUID", "id")
        if not guid:
            continue
        node_id = f"egeria_connection:{guid}"
        _add(
            node_id,
            "DataConnector",
            {**_base_props(record), "name": _first(record, "displayName", "name")},
        )
        asset = _first(record, "assetGuid", "connectsToGuid")
        if asset:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"egeria_asset:{asset}",
                    relationship="CONNECTS_TO",
                )
            )

    for record in _call(client, "list_data_flows"):
        process = _first(record, "processGuid", "process", "transformationGuid")
        source = _first(record, "sourceGuid", "source", "fromGuid")
        target = _first(record, "targetGuid", "target", "toGuid")
        if process:
            process_id = f"egeria_process:{process}"
            _add(
                process_id,
                "ProcessModel",
                {
                    "domain": "egeria",
                    "externalToolId": process,
                    "name": _first(record, "processName", "name"),
                },
            )
            if source:
                relationships.append(
                    Relationship(
                        source=f"egeria_asset:{source}",
                        target=process_id,
                        relationship="flowsTo",
                    )
                )
            if target:
                relationships.append(
                    Relationship(
                        source=process_id,
                        target=f"egeria_asset:{target}",
                        relationship="derivesFrom",
                    )
                )
        elif source and target:
            for guid, name_key, type_key in (
                (source, "sourceName", "sourceType"),
                (target, "targetName", "targetType"),
            ):
                _add(
                    f"egeria_asset:{guid}",
                    _kg_type(_first(record, type_key)),
                    {
                        "domain": "egeria",
                        "externalToolId": guid,
                        "name": _first(record, name_key) or guid,
                    },
                )
            relationships.append(
                Relationship(
                    source=f"egeria_asset:{source}",
                    target=f"egeria_asset:{target}",
                    relationship=_flow_rel(_first(record, "label")),
                )
            )

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="Apache Egeria open metadata / glossary / governance / lineage -> KG",
)
