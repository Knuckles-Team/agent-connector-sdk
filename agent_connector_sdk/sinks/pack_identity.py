"""Bind generated ConnectorPack responses to the requested tenant and connector."""

from __future__ import annotations

from epistemic_graph.generated.connector_pack import (
    AgentLibraryMutationContext,
    PackImportResult,
    PackImportResultImported,
)


def _validate_pack_identity(
    *, tenant_id: str, connector: str, actual_tenant: str, actual_connector: str
) -> None:
    if actual_tenant != tenant_id or actual_connector != connector:
        raise ValueError(
            "ConnectorPack response does not bind the requested tenant and connector"
        )


def _validate_imported_pack_identity(
    result: PackImportResult, context: AgentLibraryMutationContext, connector: str
) -> None:
    if isinstance(result, PackImportResultImported):
        _validate_pack_identity(
            tenant_id=context.tenant_id,
            connector=connector,
            actual_tenant=result.receipt.tenant_id,
            actual_connector=result.receipt.connector,
        )
