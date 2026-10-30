"""ERPNext write-back sink (CONCEPT:AU-KG.ingest.enterprise-source-extractor).

Backfeeds the KG into ERPNext — creates inventory as Items/Assets, enriches
existing docs, and retires (disables) decommissioned ones — fail-closed
(``ERPNEXT_ENABLE_WRITE``), dry-run-first. Resolves KG nodes to Frappe doc names
via the ``externalToolId``/``domain="erpnext"`` federation key. Uses the
``erpnext-agent`` resource client (``create_document``/``update_document``).

ERPNext has no generic relation table, so inferred *relationships* are reported as
skipped (link them via document link-fields in a future, doctype-specific pass).
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

# KG node type → ERPNext doctype + the doctype's name field for created inventory.
_DOCTYPE_MAP: dict[str, tuple[str, str]] = {
    "technologyproduct": ("Item", "item_code"),
    "item": ("Item", "item_code"),
    "assetinstance": ("Asset", "asset_name"),
    "asset": ("Asset", "asset_name"),
    "server": ("Asset", "asset_name"),
    "hardwarenode": ("Asset", "asset_name"),
    "service": ("Asset", "asset_name"),
    "itcomponent": ("Asset", "asset_name"),
}


def _doctype_for(node_type: str) -> tuple[str, str]:
    return _DOCTYPE_MAP.get((node_type or "").lower(), ("Item", "item_code"))


def _extract_doc_name(res: Any, fallback: str | None = None) -> str | None:
    """Best-effort pull of the created Frappe doc ``name`` from the return shape."""
    if isinstance(res, str):
        return res or fallback
    for obj in (res, getattr(res, "data", None)):
        if isinstance(obj, dict):
            inner = obj.get("data")
            if isinstance(inner, dict) and inner.get("name"):
                return str(inner["name"])
            if obj.get("name"):
                return str(obj["name"])
    name = getattr(res, "name", None)
    return str(name) if name else fallback


class ErpNextSink(WritebackClientMixin):
    """Write-back sink for ERPNext Items & Assets."""

    domain = "erpnext"
    enable_flag = "ERPNEXT_ENABLE_WRITE"
    client_module = "erpnext_agent"
    client_label = "erpnext"

    def _run(self, invocation: WritebackInvocation) -> WritebackResult:
        ctx, ops, client, result, dry_run = invocation.unpack()
        resolve = ctx.resolver("erpnext")
        for c in ops.get("creations") or []:
            self._op_creations(ctx, client, result, c, resolve, dry_run=dry_run)
        for item in ops.get("enrichments") or []:
            self._op_enrichments(ctx, client, result, item, resolve, dry_run=dry_run)
        for item in ops.get("retirements") or []:
            self._op_retirements(ctx, client, result, item, resolve, dry_run=dry_run)
        for _edge in ops.get("inferences") or []:
            self._op_inferences(ctx, client, result, _edge, resolve, dry_run=dry_run)
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
        """creations — new Items / Assets.."""
        name = c.get("name")
        if not name:
            return
        doctype, name_field = _doctype_for(c.get("type", ""))
        doctype = c.get("doctype") or doctype
        data = {name_field: name, **(c.get("attributes") or {})}
        if dry_run:
            result.proposals.append(
                {"op": "create_document", "doctype": doctype, "name": name}
            )
            return
        try:
            res = client.create_document(doctype, data)
            result.created += 1
            ctx.stamp_external_id(
                c.get("node"),
                self.domain,
                _extract_doc_name(res, fallback=name),
                node_type=c.get("type", ""),
            )
        except Exception:
            logger.debug("erpnext create_document failed", exc_info=True)
            result.errors += 1

    def _op_enrichments(
        self,
        ctx: Any,
        client: Any,
        result: WritebackResult,
        item: dict[str, Any],
        resolve: Any,
        *,
        dry_run: bool,
    ) -> None:
        """enrichments — update fields on existing docs.."""
        doc_name = resolve(item.get("node"))
        attrs = item.get("attributes") or {}
        doctype = item.get("doctype") or "Item"
        if not (doc_name and attrs):
            result.skipped += 1
            return
        if dry_run:
            result.proposals.append(
                {"op": "update_document", "doctype": doctype, "name": doc_name}
            )
            return
        try:
            client.update_document(doctype, doc_name, attrs)
            result.enriched += 1
        except Exception:
            logger.debug("erpnext update_document failed", exc_info=True)
            result.errors += 1

    def _op_retirements(
        self,
        ctx: Any,
        client: Any,
        result: WritebackResult,
        item: dict[str, Any],
        resolve: Any,
        *,
        dry_run: bool,
    ) -> None:
        """retirements — disable the doc.."""
        doc_name = resolve(item.get("node"))
        doctype = item.get("doctype") or "Item"
        if not doc_name:
            result.skipped += 1
            return
        if dry_run:
            result.proposals.append(
                {"op": "retire", "doctype": doctype, "name": doc_name}
            )
            return
        try:
            client.update_document(doctype, doc_name, {"disabled": 1})
            result.retired += 1
        except Exception:
            logger.debug("erpnext retire failed", exc_info=True)
            result.errors += 1

    def _op_inferences(
        self,
        ctx: Any,
        client: Any,
        result: WritebackResult,
        _edge: dict[str, Any],
        resolve: Any,
        *,
        dry_run: bool,
    ) -> None:
        """ERPNext has no generic relation table — inferred relations are skipped.."""
        result.skipped += 1


register_sink(ErpNextSink())
