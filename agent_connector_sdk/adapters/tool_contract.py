"""Shared discover/describe plumbing for declarative ``ToolPreset`` adapters.

Every ``mcp_tool``-shaped source adapter (documents, typed entities, or an
event feed) verifies its live tool against a pinned compatibility fingerprint
the same way, and declares its capability descriptor from the same preset
fields. Both :class:`agent_connector_sdk.adapters.mcp_tool.McpToolSourceAdapter`
and :class:`agent_connector_sdk.adapters.event_feed.EventFeedSourceAdapter`
import this module rather than each re-inlining the verify-then-describe
sequence.
"""

from __future__ import annotations

from agent_connector_sdk.contracts import CapabilityDescriptor, StreamDescriptor
from agent_connector_sdk.manifest.live_contract import validate_preset_tool_contract
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.manifest.tool_schema import ToolSchemaContractError
from agent_connector_sdk.ports.errors import SourceContractError
from agent_connector_sdk.ports.session import McpSession

__all__ = ["describe_preset_adapter", "discover_tool_backed_stream"]


def describe_preset_adapter(
    kind: str, preset: ToolPreset, *, incremental: bool
) -> CapabilityDescriptor:
    """The capability descriptor every ``mcp_tool``-shaped adapter declares."""
    return CapabilityDescriptor(
        kind=kind,
        pagination=(preset.pagination,),
        incremental=incremental,
        certified_for_ingestion=True,
    )


async def discover_tool_backed_stream(
    session: McpSession,
    preset: ToolPreset,
    *,
    pinned_schema_sha256: str,
    identifier_fields: tuple[str, ...] | None = None,
) -> tuple[str, StreamDescriptor]:
    """Verify ``preset``'s live tool and describe the stream it extracts.

    ``identifier_fields`` names the schema contract's identifier for adapters
    whose records carry one; adapters without a per-record identifier (such
    as an event feed) leave it unset.

    Returns the verified compatibility fingerprint alongside the descriptor
    so a caller can pin it for later extraction calls.

    Raises:
        SourceContractError: the live tool does not satisfy its pinned
            contract, or was not verified.
    """
    try:
        contract = validate_preset_tool_contract(
            await session.list_tools(),
            tool_name=preset.tool,
            presets=(preset,),
            expected_schema_sha256=pinned_schema_sha256,
        )
    except ToolSchemaContractError as exc:
        raise SourceContractError(str(exc)) from exc
    schema_contract = contract.schema_contract
    if identifier_fields is not None:
        schema_contract = schema_contract.model_copy(
            update={"identifier_fields": identifier_fields}
        )
    descriptor = StreamDescriptor(
        stream=preset.name,
        tool=preset.tool,
        schema_sha256=contract.compatibility_sha256,
        schema_contract=schema_contract,
        evolution_policy=preset.evolution_policy,
    )
    return contract.compatibility_sha256, descriptor
