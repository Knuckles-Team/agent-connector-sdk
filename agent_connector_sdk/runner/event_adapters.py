"""Compose authorized event adapters from live connector declarations."""

from agent_connector_sdk.discovery import (
    SOURCE_ADAPTER_GROUP,
    ActivationPolicy,
    load_extension,
)
from agent_connector_sdk.manifest.declaration import SyncContract
from agent_connector_sdk.manifest.live_contract import validate_preset_tool_contract
from agent_connector_sdk.manifest.model import SyncSpec
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.session import McpSession
from agent_connector_sdk.ports.source_adapter import SourceAdapter
from agent_connector_sdk.runner.descriptors import ConnectorDescriptor
from agent_connector_sdk.runner.errors import RunnerConfigurationError


def _ordinary_names(
    names: tuple[str, ...], specs: dict[str, SyncSpec]
) -> tuple[str, ...]:
    return tuple(name for name in names if specs[name].feed_kind is None)


def _event_adapter(
    spec: SyncSpec,
    descriptor: ConnectorDescriptor,
    tools: object,
    *,
    policy: ActivationPolicy,
) -> SourceAdapter:
    preset = ToolPreset.from_mapping(spec.preset, dict(spec.raw))
    pin = validate_preset_tool_contract(
        tools, tool_name=preset.tool, presets=(preset,)
    ).compatibility_sha256
    factory = load_extension(SOURCE_ADAPTER_GROUP, spec.feed_kind or "", policy=policy)
    if not callable(factory):
        raise RunnerConfigurationError("event adapter entry point is not callable")
    adapter = factory(
        preset,
        connector=descriptor.connector,
        tool_schema_sha256=pin,
        mapping_reference=descriptor.resolved_mapping_reference,
    )
    if not isinstance(adapter, SourceAdapter):
        raise RunnerConfigurationError("event adapter entry point has the wrong port")
    return adapter


async def _build_event_adapters(
    descriptor: ConnectorDescriptor,
    session: McpSession,
    contract: SyncContract,
    *,
    policy: ActivationPolicy | None,
) -> dict[str, SourceAdapter]:
    """Activate only explicitly declared event kinds under the host policy."""
    selected = set(descriptor.presets or (spec.preset for spec in contract.sync))
    events = [
        spec for spec in contract.sync if spec.preset in selected and spec.feed_kind
    ]
    if not events:
        return {}
    if policy is None:
        raise RunnerConfigurationError("event adapters require an activation policy")
    tools = await session.list_tools()
    return {
        spec.preset: _event_adapter(spec, descriptor, tools, policy=policy)
        for spec in events
    }
