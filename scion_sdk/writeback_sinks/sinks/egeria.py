"""Egeria write-back sink (CONCEPT:AU-KG.ingest.enterprise-source-extractor).

Catalogs KG-derived entities into the Egeria open-metadata estate as governed
assets — the first-class write-back twin of the Egeria harvest, now on the unified
write-back surface. Standard tier, fail-closed (``EGERIA_ENABLE_WRITE``),
dry-run-first.
"""

from __future__ import annotations

import logging
from typing import Any

from ..core import (
    WritebackClientMixin,
    WritebackInvocation,
    WritebackResult,
    register_sink,
)

logger = logging.getLogger(__name__)

# KG node type → Egeria open-metadata asset type.
_ASSET_TYPE = {
    "application": "DeployedSoftwareComponent",
    "itcomponent": "DeployedSoftwareComponent",
    "service": "SoftwareServer",
    "server": "SoftwareServer",
    "dataobject": "DeployedDatabaseSchema",
    "topic": "KafkaTopic",
    "configurationitem": "DeployedSoftwareComponent",
    "assetinstance": "DeployedSoftwareComponent",
    "technologyproduct": "DeployedSoftwareComponent",
}


class EgeriaSink(WritebackClientMixin):
    domain = "egeria"
    enable_flag = "EGERIA_ENABLE_WRITE"
    risk_tier = "standard"
    client_module = "egeria_mcp"
    client_label = "egeria"

    def _run(self, invocation: WritebackInvocation) -> WritebackResult:
        ctx, ops, client, result, dry_run = invocation.unpack()
        for c in ops.get("creations") or []:
            self._create(ctx, client, result, c, dry_run=dry_run)
        return result

    def _create(
        self,
        ctx: Any,
        client: Any,
        result: WritebackResult,
        c: dict[str, Any],
        *,
        dry_run: bool,
    ) -> None:
        name = c.get("name")
        if not name:
            return
        asset_type = c.get("asset_type") or _ASSET_TYPE.get(
            (c.get("type") or "").lower(), "DeployedSoftwareComponent"
        )
        qn = c.get("qualified_name") or f"KG::{c.get('type', 'Asset')}::{name}"
        if dry_run:
            result.proposals.append(
                {"op": "create_asset", "type": asset_type, "name": name}
            )
            return
        # X5 (CONCEPT:AU-KG.temporal.bi-temporal-memory-layers): additional_properties
        # is Egeria's free-form provenance channel — the KG-state instant this
        # asset was derived from rides along in the SAME live payload.
        props: dict[str, Any] = {"source": "arbora"}
        if ctx.as_of:
            props["as_of"] = ctx.as_of
        try:
            res = client.create_asset(
                asset_type,
                qn,
                name,
                description=c.get("description", "KG-derived asset."),
                additional_properties=props,
            )
        except Exception:
            logger.debug("egeria create_asset failed", exc_info=True)
            result.errors += 1
            return
        if isinstance(res, dict) and res.get("guid"):
            result.created += 1
            ctx.stamp_external_id(
                c.get("node"),
                self.domain,
                str(res.get("guid")),
                node_type=c.get("type", ""),
            )
        else:
            result.errors += 1


register_sink(EgeriaSink())
