"""ARIS process/EA vendor extractor (SDK-SOURCE-INGEST-R006.29).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.aris``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
Software AG ARIS models map to the canonical ArchiMate concepts so ARIS folds
into the same cross-vendor crosswalk as Camunda (BPM) and LeanIX/ArchiMate
(EA):

    process model       -> ``BusinessProcess``       id=aris_model:{id}
    architecture model  -> ``ApplicationComponent``  id=aris_model:{id}

A model record carrying a Camunda key or Egeria GUID gets an ``ALIGNED_WITH``
equivalence relationship to its ``bpmn_process:{key}``/``egeria_process:{guid}``
twin, so an ARIS process and its Camunda/Egeria twin collapse to one logical
identity under reasoning. The ARIS client is injected (duck-typed) via
``config["client"]``, expected to expose ``list_models()``. This module
performs no network calls itself.

Scope note: the agent-utilities source additionally lifts each process
model's step-level EPC structure (functions/rule-operators/events ->
``BusinessTask``/``FLOWS_TO``) when the client also serves
``list_model_objects``/``list_model_connections``, via a graph-collapse
algorithm shared with the Camunda extractor. This port carries over the
model-level mapping and crosswalk only; the step-level EPC lift is not ported
in this change (follow-up).
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "aris"

# Model-type substrings marking a process (BPM) model vs an architecture model.
_BPM_HINTS = ("process", "epc", "bpmn", "value", "vad")


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
    """Call a no-arg client method if present, returning a list (tolerant)."""
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
        result = result.get("items") or result.get("models") or result.get("data") or []
    return list(result) if result else []


def _is_process(model_type: str) -> bool:
    text = (model_type or "").lower()
    return any(hint in text for hint in _BPM_HINTS)


def extract(config: Any) -> ChangeSet:
    """Extract ARIS models into a uniform ``ChangeSet``.

    Process models become canonical ``BusinessProcess`` entities;
    architecture models become ``ApplicationComponent`` entities, so they
    cross-link with the BPM and EA cohorts respectively.
    """
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    entities: list[Entity] = []
    relationships: list[Relationship] = []

    for record in _call(client, "list_models"):
        model_id = _first(record, "id", "modelId", "name")
        if not model_id:
            continue
        model_type = _first(record, "type", "modelType") or "Model"
        is_process = _is_process(model_type)
        label = "BusinessProcess" if is_process else "ApplicationComponent"
        model_node_id = f"aris_model:{model_id}"
        properties: dict[str, Any] = {
            "name": _first(record, "name", "id"),
            "model_type": model_type,
            "capability": "bpm" if is_process else "enterprise-architecture",
        }
        camunda_key = _first(record, "camundaKey", "camunda_key", "bpmnProcessId")
        egeria_guid = _first(record, "egeriaGuid", "egeria_guid", "externalToolId")
        if camunda_key:
            properties["externalToolId"] = camunda_key
            relationships.append(
                Relationship(
                    source=model_node_id,
                    target=f"bpmn_process:{camunda_key}",
                    relationship="ALIGNED_WITH",
                )
            )
        elif egeria_guid:
            properties["externalToolId"] = egeria_guid
            relationships.append(
                Relationship(
                    source=model_node_id,
                    target=f"egeria_process:{egeria_guid}",
                    relationship="ALIGNED_WITH",
                )
            )
        entities.append(
            Entity(id=model_node_id, node_type=label, properties=properties)
        )

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="ARIS models (process/architecture + Camunda/Egeria crosswalk) -> KG",
)
