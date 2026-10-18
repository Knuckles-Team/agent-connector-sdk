"""Register a connector's MCP tool surface: one tool per API operation.

The one entry point a connector's server module calls
(SDK-CONNECTOR-CONTROL-R020). Given the connector's API client (``client_cls``
and ``get_client``, plus one ``verbose_targets`` entry per further client),
it registers one typed, annotated tool per client operation through
:func:`agent_connector_sdk.mcp.method_tools.register_method_tools`. A fleet
gateway scales the catalog through lazy ``find`` and load; every tool is
tagged :data:`GATED_TAG` so it is revealed on demand.

Registrars (``tool_registry``, ``tools_module`` or ``registrars``) still run
for tools that are not client-method wrappers, such as KG ingest or GraphQL
tools. A registrar tool that routes an ``action`` string is never dropped: when the
operation tools register, it is split into one typed tool per action
(:mod:`agent_connector_sdk.mcp.action_split`), except actions a per-operation
tool already serves (same name, same client method or same table entry); the
operation tool wins and the decision is in the registration report
(:func:`agent_connector_sdk.mcp.action_split.action_split_report`). The caller
may opt in with ``action_dispatch=True`` to keep it whole for compatibility.
No environment mode selects the surface; ``MCP_TOOL_MODE`` does not exist.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_connector_sdk.config import setting
from agent_connector_sdk.ingest.sources import (
    load_ingest_sources,
    register_ingest_sources_tool,
)
from agent_connector_sdk.manifest.package_validation import MANIFEST_FILE_NAME
from agent_connector_sdk.mcp.action_split import SPLIT_ACTION_TAG, split_action_tool
from agent_connector_sdk.mcp.method_tools import (
    GATED_TAG,
    GRANULAR_TAG,
    operation_tool_names,
    register_method_tools,
)

__all__ = [
    "ACTION_DISPATCH_TAG",
    "GATED_TAG",
    "GATED_TOOLS_ATTRIBUTE",
    "GRANULAR_TAG",
    "CondensedEntry",
    "gated_tool_names",
    "operation_prefix",
    "register_tool_surface",
    "registered_tools",
]

#: ``(tag, toggle_setting, register_fn)`` for one condensed tool registrar.
CondensedEntry = tuple[str, str, Callable[[Any], Any]]

#: Tag stamped on a registrar tool kept as an opt-in action-dispatch tool.
ACTION_DISPATCH_TAG = "action-dispatch"
#: Server attribute recording the names tagged :data:`GATED_TAG`.
GATED_TOOLS_ATTRIBUTE = "_intent_gated_tools"

_TOGGLES_ATTRIBUTE = "_condensed_tool_toggles"
_REGISTRAR_NAME = re.compile(r"register_(.+)_tools")


def registered_tools(mcp: Any) -> dict[str, Any]:
    """``{tool_name: tool}`` currently registered on the server's local provider."""
    provider = getattr(mcp, "_local_provider", None)
    components = getattr(provider, "_components", None)
    if not isinstance(components, dict):
        return {}
    return {
        value.name: value
        for key, value in components.items()
        if str(key).startswith("tool:") and getattr(value, "name", None)
    }


def gated_tool_names(mcp: Any) -> set[str]:
    """Tool names tagged :data:`GATED_TAG`."""
    return set(getattr(mcp, GATED_TOOLS_ATTRIBUTE, ()) or ())


def _entry(item: Any) -> CondensedEntry:
    if isinstance(item, tuple | list):
        if len(item) != 3 or not callable(item[2]):
            raise ValueError(
                "a registrar entry must be (tag, toggle_setting, register_fn)"
            )
        return str(item[0]), str(item[1]), item[2]
    if not callable(item):
        raise ValueError("a registrar must be callable or a (tag, setting, fn) entry")
    match = _REGISTRAR_NAME.fullmatch(getattr(item, "__name__", ""))
    tag = match.group(1) if match else str(getattr(item, "__name__", "tools"))
    return tag, f"{tag.upper()}TOOL", item


def _condensed_entries(
    tool_registry: list[Any] | None, tools_module: Any, registrars: list[Any] | None
) -> list[CondensedEntry]:
    if tool_registry:
        return [_entry(item) for item in tool_registry]
    if tools_module is None:
        return [_entry(item) for item in registrars or []]
    return [
        _entry(getattr(tools_module, name))
        for name in sorted(vars(tools_module))
        if _REGISTRAR_NAME.fullmatch(name)
        and name != "register_tool_surface"
        and callable(getattr(tools_module, name))
    ]


def _register_condensed(mcp: Any, entries: list[CondensedEntry]) -> list[str]:
    toggles: dict[str, str] = getattr(mcp, _TOGGLES_ATTRIBUTE, {})
    gated: set[str] = getattr(mcp, GATED_TOOLS_ATTRIBUTE, set())
    registered_tags: list[str] = []
    for tag, toggle, register_fn in entries:
        if not setting(toggle, True):
            continue
        before = set(registered_tools(mcp))
        register_fn(mcp)
        added = {
            name: tool
            for name, tool in registered_tools(mcp).items()
            if name not in before
        }
        for name, tool in added.items():
            tool.tags.update({tag, GRANULAR_TAG, GATED_TAG})
            toggles[name] = toggle
        gated.update(added)
        registered_tags.append(tag)
    setattr(mcp, _TOGGLES_ATTRIBUTE, toggles)
    setattr(mcp, GATED_TOOLS_ATTRIBUTE, gated)
    return registered_tags


_SERVICE_SUFFIXES = ("-mcp", "-agent", "-api", "-server")


def operation_prefix(service: str, tool_prefix: str | None = None) -> str:
    """The operation-tool name prefix: ``tool_prefix``, else the service name.

    The service name drops a trailing ``-mcp``/``-agent``/``-api``/``-server``
    and becomes snake_case, so ``home-assistant-agent`` -> ``home_assistant``.
    """
    if tool_prefix:
        return tool_prefix
    name = service
    for suffix in _SERVICE_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)]
            break
    return re.sub(r"\W+", "_", name).strip("_").lower()


def _is_action_dispatch(tool: Any) -> bool:
    """Whether a registered tool routes an ``action`` string to client methods."""
    schema = getattr(tool, "parameters", None) or {}
    return "action" in (schema.get("properties") or {})


def _register_operations(
    mcp: Any,
    *,
    prefix: str,
    client_cls: type | None,
    get_client: Any,
    manifest: list[dict[str, Any]] | None,
    verbose_targets: list[dict[str, Any]] | None,
    result_coercer: Callable[[Any], Any] | None,
) -> list[str]:
    targets: list[dict[str, Any]] = []
    if client_cls is not None and get_client is not None:
        targets.append(
            {"client_cls": client_cls, "get_client": get_client, "manifest": manifest}
        )
    targets.extend(verbose_targets or [])
    names: list[str] = []
    for target in targets:
        if "client_cls" not in target or "get_client" not in target:
            raise ValueError("a verbose target needs 'client_cls' and 'get_client'")
        names += register_method_tools(
            mcp,
            target["client_cls"],
            target["get_client"],
            prefix=str(target.get("prefix") or prefix),
            manifest=target.get("manifest"),
            result_coercer=target.get("result_coercer", result_coercer),
        )
    return names


def _settle_action_tools(mcp: Any, *, operations: dict[str, str], keep: bool) -> None:
    """Keep (``keep``) or split every action-routed registrar tool; never drop one.

    ``operations`` maps each client method that will be served as an operation
    tool to that tool's name; a split action that duplicates one is covered by
    it and recorded in the registration report.
    """
    gated: set[str] = getattr(mcp, GATED_TOOLS_ATTRIBUTE, set())
    for name, tool in list(registered_tools(mcp).items()):
        if not _is_action_dispatch(tool) or SPLIT_ACTION_TAG in (tool.tags or set()):
            continue
        if keep:
            tool.tags.add(ACTION_DISPATCH_TAG)
            continue
        added = split_action_tool(
            mcp,
            name,
            tool,
            operations=operations,
            taken=set(registered_tools(mcp)) - {name},
        )
        if name not in added:
            gated.discard(name)
        gated.update(added)
    setattr(mcp, GATED_TOOLS_ATTRIBUTE, gated)


def _operation_methods(
    prefix: str,
    client_cls: type | None,
    manifest: list[dict[str, Any]] | None,
    verbose_targets: list[dict[str, Any]] | None,
) -> dict[str, str]:
    """``{method: tool_name}`` for every operation tool about to be served."""
    targets = [(client_cls, prefix, manifest)] if client_cls is not None else []
    targets += [
        (t["client_cls"], str(t.get("prefix") or prefix), t.get("manifest"))
        for t in verbose_targets or []
        if "client_cls" in t
    ]
    names: dict[str, str] = {}
    for cls, target_prefix, target_manifest in targets:
        for method, tool in operation_tool_names(
            cls, prefix=target_prefix, manifest=target_manifest
        ).items():
            names.setdefault(method, tool)
    return names


def _package_root(owner: Any) -> Path | None:
    """The directory of the top-level package that defines ``owner``."""
    module_name = getattr(owner, "__module__", None) or getattr(owner, "__name__", "")
    top = str(module_name).split(".", 1)[0]
    module = sys.modules.get(top)
    location = getattr(module, "__file__", None)
    return Path(location).parent if location else None


def _register_declared_sources(mcp: Any, prefix: str, root: Path | None) -> None:
    """Serve the package's ingest-source declaration when it ships one."""
    if root is None:
        return
    declaration = load_ingest_sources(root)
    if declaration is not None:
        register_ingest_sources_tool(mcp, prefix, declaration)
    _register_packaged_manifest(mcp, root)


def _register_packaged_manifest(mcp: Any, root: Path) -> None:
    """Serve ``<package>/connector_manifest.yml`` as ``manifest://connector``.

    SDK-SOURCE-INGEST-R004.25: fleet onboarding captures this resource as the
    pack's manifest, whose ``schema_mappings`` the engine admits source records
    under. A server that already serves the URI keeps its own resource.
    """
    from agent_connector_sdk.mcp.content import MANIFEST_RESOURCE_URI, _file_resource

    path = root / MANIFEST_FILE_NAME
    if not path.is_file():
        return
    served = getattr(getattr(mcp, "_local_provider", None), "_components", {})
    if any(str(key).endswith(MANIFEST_RESOURCE_URI) for key in served):
        return
    mcp.add_resource(_file_resource(MANIFEST_RESOURCE_URI, path, "text/yaml"))


def register_tool_surface(
    mcp: Any,
    *,
    service: str,
    client_cls: type | None = None,
    get_client: Any = None,
    tool_registry: list[Any] | None = None,
    tools_module: Any = None,
    registrars: list[Any] | None = None,
    manifest: list[dict[str, Any]] | None = None,
    tool_prefix: str | None = None,
    verbose_targets: list[dict[str, Any]] | None = None,
    verbose_register: Callable[[Any], None] | None = None,
    action_providers: dict[str, Any] | None = None,
    action_dispatch: bool = False,
    result_coercer: Callable[[Any], Any] | None = None,
    package_root: Path | None = None,
) -> list[str]:
    """Register one tool per API operation, plus the connector's other tools.

    Operation tools: one per public method of ``client_cls`` (resolved per call
    through ``get_client``) and of each ``verbose_targets`` entry
    (``{client_cls, get_client, prefix?, manifest?, result_coercer?}``), named
    ``<prefix>_<operation>`` where ``prefix`` is ``tool_prefix`` or derived
    from ``service`` (:func:`operation_prefix`). ``manifest`` carries the
    OpenAPI operation entries for ``client_cls``.

    Registrar tools come from exactly one of ``tool_registry``
    (``[(tag, toggle_setting, fn)]``), ``tools_module`` (every
    ``register_<tag>_tools`` callable on it) or ``registrars``; each runs
    unless its ``<TAG>TOOL`` setting is false. A registrar tool with an
    ``action`` input is an action-dispatch tool: when operation tools
    register it is split into one typed ``<tool>_<action>`` tool per action
    (an action whose split name is an operation tool's name, or that resolves
    to a served client method, is covered by that operation tool and listed
    in the registration report instead of raising),
    or kept whole with a warning when its actions cannot be enumerated;
    ``action_dispatch=True`` keeps it whole, tagged :data:`ACTION_DISPATCH_TAG`. With no client, registrar tools are the whole
    surface. Every tool is tagged :data:`GRANULAR_TAG` and :data:`GATED_TAG`.

    A package that ships ``ontology/ingest_sources.json`` also serves its
    declared sources as the read-only ``<prefix>_ingest_sources`` tool
    (SDK-SOURCE-INGEST-R004.21). ``package_root`` names that package; it
    defaults to the top-level package of ``client_cls`` or ``tools_module``.

    ``verbose_register``, when given, runs last (SDK-CONNECTOR-CONTROL-R032)
    and must not replace a registered name. ``action_providers`` is accepted
    and ignored.

    Returns:
        The registrar tags that registered.

    Raises:
        ValueError: a registrar entry is malformed, or two different tools
            (neither a covered split) share a name.
    """
    del action_providers
    tags = _register_condensed(
        mcp, _condensed_entries(tool_registry, tools_module, registrars)
    )
    has_client = (client_cls is not None and get_client is not None) or bool(
        verbose_targets
    )
    prefix = operation_prefix(service, tool_prefix)
    if has_client:
        # Split action-routed tools first so an operation may reuse a name.
        _settle_action_tools(
            mcp,
            operations=_operation_methods(
                prefix, client_cls, manifest, verbose_targets
            ),
            keep=action_dispatch,
        )
    operations = _register_operations(
        mcp,
        prefix=prefix,
        client_cls=client_cls,
        get_client=get_client,
        manifest=manifest,
        verbose_targets=verbose_targets,
        result_coercer=result_coercer,
    )
    if operations:
        gated: set[str] = getattr(mcp, GATED_TOOLS_ATTRIBUTE, set())
        setattr(mcp, GATED_TOOLS_ATTRIBUTE, gated | set(operations))
    _register_declared_sources(
        mcp, prefix, package_root or _package_root(client_cls or tools_module)
    )
    if verbose_register is not None:
        before = registered_tools(mcp)
        verbose_register(mcp)
        after = registered_tools(mcp)
        collisions = {
            name for name in before if name in after and after[name] is not before[name]
        }
        if collisions:
            raise ValueError(
                f"verbose tool name collides with a registered tool: {sorted(collisions)}"
            )
    return tags
