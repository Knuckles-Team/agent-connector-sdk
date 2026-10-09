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

The field-mapping helpers live in ``egeria_mappers`` and the per-record-type
entity builders in ``egeria_entities``; this module only resolves the client,
fans its list-methods out to those builders, and registers the extractor.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor
from agent_connector_sdk.vendor_extractors.egeria_entities import (
    _ChangeSetBuilder,
    _add_assets,
    _add_data_flows,
    _add_governance_definitions,
    _add_single_relation,
    _add_software_servers,
)

CATEGORY = "egeria"


def _get(record: Any, key: str, default: Any = None) -> Any:
    """Tolerant field access for dict records (or attr-style objects)."""
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _call_result(method: Any) -> Any:
    """Invoke a duck-typed accessor method, tolerating a required-arg form."""
    for call in (lambda: method(), lambda: method({})):
        try:
            return call()
        except TypeError:
            continue
        except Exception:
            return None
    return None


def _call(client: Any, name: str) -> list[Any]:
    """Call a client list-method if present, returning a list (tolerant)."""
    method = getattr(client, name, None)
    if not callable(method):
        return []
    result = _call_result(method)
    if result is None:
        return []
    if isinstance(result, dict):
        result = (
            result.get("items") or result.get("results") or result.get("elements") or []
        )
    return list(result) if result else []


def extract(config: Any) -> ChangeSet:
    """Extract Egeria open-metadata artifacts into a uniform ``ChangeSet``."""
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    builder = _ChangeSetBuilder()
    _add_assets(_call(client, "list_assets"), builder)
    _add_single_relation(
        _call(client, "list_glossary_categories"),
        builder,
        id_prefix="egeria_category",
        node_type="GlossaryCategory",
        extra_props_keys=(("name", ("displayName", "name")),),
        relation_keys=("parentCategoryGuid", "parentGuid"),
        relation_prefix="egeria_category",
        relation_type="PART_OF",
    )
    _add_single_relation(
        _call(client, "list_glossary_terms"),
        builder,
        id_prefix="egeria_term",
        node_type="Concept",
        extra_props_keys=(
            ("name", ("displayName", "name")),
            ("summary", ("summary", "description")),
        ),
        relation_keys=("categoryGuid", "category"),
        relation_prefix="egeria_category",
        relation_type="IN_CATEGORY",
    )
    _add_governance_definitions(_call(client, "list_governance_definitions"), builder)
    _add_software_servers(_call(client, "list_software_servers"), builder)
    _add_single_relation(
        _call(client, "list_connections"),
        builder,
        id_prefix="egeria_connection",
        node_type="DataConnector",
        extra_props_keys=(("name", ("displayName", "name")),),
        relation_keys=("assetGuid", "connectsToGuid"),
        relation_prefix="egeria_asset",
        relation_type="CONNECTS_TO",
    )
    _add_data_flows(_call(client, "list_data_flows"), builder)

    return ChangeSet(
        entities=tuple(builder.entities), relationships=tuple(builder.relationships)
    )


register_vendor_extractor(
    CATEGORY,
    extract,
    description="Apache Egeria open metadata / glossary / governance / lineage -> KG",
)
