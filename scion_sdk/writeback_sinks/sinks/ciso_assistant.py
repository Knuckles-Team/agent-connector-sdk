"""CISO Assistant write-back sink (CONCEPT:AU-KG.enrichment.ciso-2 / CISO-003).

Pushes KG-derived governance entities back into the intuitem **CISO Assistant**
GRC estate — the first-class write-back twin of the CISO Assistant harvest, on the
unified write-back surface. Standard tier, fail-closed
(``CISO_ASSISTANT_ENABLE_WRITE``), dry-run-first.

A KG node of a governance type (``Policy``/``Control``/``Asset``/``Finding``/
``SecurityException``/``Entity``) becomes the matching CISO object via the
generated ``api_*_create`` method. CISO requires every object to live in a folder
(domain); the operator supplies a default folder id in the op payload
(``folder``) or per-creation, otherwise the creation is reported as skipped rather
than guessed.
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

# KG node type → (CISO Assistant create method, object label).
_CREATE = {
    "policy": ("api_policies_create", "policy"),
    "control": ("api_applied_controls_create", "applied control"),
    "appliedcontrol": ("api_applied_controls_create", "applied control"),
    "asset": ("api_assets_create", "asset"),
    "finding": ("api_findings_create", "finding"),
    "securityexception": ("api_security_exceptions_create", "security exception"),
    "entity": ("api_entities_create", "entity"),
}


class CisoAssistantSink(WritebackClientMixin):
    domain = "ciso_assistant"
    enable_flag = "CISO_ASSISTANT_ENABLE_WRITE"
    risk_tier = "standard"
    client_module = "ciso_assistant_api"
    client_label = "ciso_assistant"

    def _run(self, invocation: WritebackInvocation) -> WritebackResult:
        _, ops, client, result, dry_run = invocation.unpack()
        default_folder = ops.get("folder")
        for c in ops.get("creations") or []:
            self._create(client, result, c, default_folder, dry_run=dry_run)
        return result

    def _create(
        self,
        client: Any,
        result: WritebackResult,
        c: dict[str, Any],
        default_folder: Any,
        *,
        dry_run: bool,
    ) -> None:
        name = c.get("name")
        spec = _CREATE.get((c.get("type") or "").lower())
        if not name or spec is None:
            result.skipped += 1
            return
        method_name, label = spec
        if dry_run:
            result.proposals.append(
                {"op": f"create_{label.replace(' ', '_')}", "name": name}
            )
            return
        folder = c.get("folder") or default_folder
        method = getattr(client, method_name, None)
        if not folder or not callable(method):
            # CISO objects must belong to a folder; never guess one.
            result.skipped += 1
            return
        payload = _payload(c, name, folder)
        try:
            res = method(body=payload)
            data = getattr(res, "data", res)
            created = isinstance(data, dict) and (data.get("id") or data.get("uuid"))
        except Exception:
            logger.debug("ciso_assistant create failed", exc_info=True)
            result.errors += 1
            return
        if created:
            result.created += 1
        else:
            result.errors += 1


def _payload(c: dict[str, Any], name: str, folder: Any) -> dict[str, Any]:
    payload = {
        "name": name,
        "folder": folder,
        "description": c.get("description", "KG-derived governance object."),
    }
    if c.get("ref_id"):
        payload["ref_id"] = c["ref_id"]
    return payload


register_sink(CisoAssistantSink())
