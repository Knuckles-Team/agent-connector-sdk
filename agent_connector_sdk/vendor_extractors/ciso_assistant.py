"""CISO Assistant GRC vendor extractor (SDK-SOURCE-INGEST-R006.27).

Ported from
``agent_utilities.knowledge_graph.enrichment.extractors.ciso_assistant`` onto
this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
intuitem CISO Assistant GRC records (policies, controls, risks, threats,
assessments, frameworks, assets, incidents, third-party entities) become the
same canonical governance entity types the Egeria extractor emits, so CISO
Assistant data reconciles with the Egeria/Camunda crosswalk:

    policy                         -> ``Policy``               ciso_assistant_policy:{id}
    applied / reference control    -> ``Control``              ciso_assistant_control:{id}
    risk scenario                  -> ``Risk``                 ciso_assistant_risk:{id}
    threat                         -> ``Threat``                ciso_assistant_threat:{id}
    risk assessment                -> ``RiskAssessment``        ciso_assistant_risk_assessment:{id}
    compliance assessment / audit  -> ``ComplianceAssessment``  ciso_assistant_compliance_assessment:{id}
    framework                      -> ``Framework``             ciso_assistant_framework:{id}
    asset                          -> ``Asset``                 ciso_assistant_asset:{id}
    incident                       -> ``Incident``              ciso_assistant_incident:{id}
    security exception / finding   -> ``SecurityException`` / ``Finding``
    third-party entity             -> ``Entity``                ciso_assistant_entity:{id}

Every entity carries ``domain="ciso_assistant"`` + ``externalToolId`` (the
CISO uuid) + ``qualifiedName`` (the CISO ``urn``/``ref_id``). A record
carrying an explicit Egeria GUID or Camunda/BPMN process id emits an
``ALIGNED_WITH`` equivalence relationship, exactly as the Camunda extractor
does. The client is injected (duck-typed) via ``config["client"]``; this
module performs no network calls itself.

The field-mapping helpers live in ``ciso_assistant_mappers`` and the
per-record-type entity builders in ``ciso_assistant_entities``; this module
only resolves the client, fans it out to those builders, and registers the
extractor.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet
from agent_connector_sdk.vendor_extractors.ciso_assistant_entities import (
    _ChangeSetBuilder,
    _add_compliance_assessments,
    _add_risk_scenarios,
    _add_simple_kinds,
)
from agent_connector_sdk.vendor_extractors.ciso_assistant_mappers import _get
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "ciso_assistant"


def extract(config: Any) -> ChangeSet:
    """Extract CISO Assistant GRC artifacts into a uniform ``ChangeSet``."""
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    builder = _ChangeSetBuilder()
    _add_simple_kinds(client, builder)
    _add_risk_scenarios(client, builder)
    _add_compliance_assessments(client, builder)

    return ChangeSet(
        entities=tuple(builder.entities), relationships=tuple(builder.relationships)
    )


register_vendor_extractor(
    CATEGORY,
    extract,
    description="intuitem CISO Assistant GRC (policies/controls/risks/assessments) -> KG",
)
