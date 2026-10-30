"""ArchiMate model write-back sink (CONCEPT:AU-KG.ingest.enterprise-source-extractor).

Writes KG-inferred elements/relationships back into the ArchiMate model so the
model stays a live mirror of the cross-tool reality (ServiceNow/LeanIX/Camunda all
map to ArchiMate classes). Standard tier (a local model file), fail-closed
(``ARCHIMATE_ENABLE_WRITE``), dry-run-first. Resolves KG nodes → ArchiMate element
ids via ``externalToolId``/``domain="archimate"``.
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

# UPPER_SNAKE KG rel type → ArchiMate relationship type.
_REL_TYPE = {
    "REALIZES": "Realization",
    "REALIZED_BY": "Realization",
    "SERVES": "Serving",
    "ASSIGNED_TO": "Assignment",
    "DEPENDS_ON": "Serving",
    "PART_OF": "Composition",
    "FLOWS_TO": "Flow",
    "TRIGGERS": "Triggering",
}


class ArchimateSink(WritebackClientMixin):
    domain = "archimate"
    enable_flag = "ARCHIMATE_ENABLE_WRITE"
    risk_tier = "standard"
    client_module = "archimate_mcp"
    client_label = "archimate"

    def _run(self, invocation: WritebackInvocation) -> WritebackResult:
        ctx, ops, client, result, dry_run = invocation.unpack()
        resolve = ctx.resolver("archimate")
        for c in ops.get("creations") or []:
            self._op_creations(ctx, client, result, c, resolve, dry_run=dry_run)
        for edge in ops.get("inferences") or []:
            self._op_inferences(ctx, client, result, edge, resolve, dry_run=dry_run)
        return result

    def _op_creations(
        self,
        ctx: Any,
        client: Any,
        result: WritebackResult,
        c: dict[str, Any],
        resolve: Any,
        *,
        dry_run: bool,
    ) -> None:
        """Apply one creations op.."""
        name = c.get("name")
        etype = c.get("type") or "Grouping"
        if not name:
            return
        if dry_run:
            result.proposals.append({"op": "add_element", "type": etype, "name": name})
            return
        try:
            client.add_element(
                type=etype, name=name, documentation=c.get("documentation", "")
            )
            result.created += 1
        except Exception:
            logger.debug("archimate add_element failed", exc_info=True)
            result.errors += 1

    def _op_inferences(
        self,
        ctx: Any,
        client: Any,
        result: WritebackResult,
        edge: dict[str, Any],
        resolve: Any,
        *,
        dry_run: bool,
    ) -> None:
        """Apply one inferences op.."""
        src = resolve(edge.get("source"))
        tgt = resolve(edge.get("target"))
        rel = _REL_TYPE.get(
            str(edge.get("rel_type") or edge.get("type")), "Association"
        )
        if not (src and tgt):
            result.skipped += 1
            return
        if dry_run:
            result.proposals.append(
                {
                    "op": "add_relationship",
                    "source": src,
                    "target": tgt,
                    "type": rel,
                }
            )
            return
        try:
            client.add_relationship(src, tgt, rel)
            result.relations_written += 1
        except Exception:
            logger.debug("archimate add_relationship failed", exc_info=True)
            result.errors += 1


register_sink(ArchimateSink())
