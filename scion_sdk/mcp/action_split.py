"""Split hand-written action-routed tools into one typed tool per action.

A registrar tool that takes an ``action`` argument used to be dropped as soon as
per-operation client tools registered. That silently removed every hand-written
tool whose actions were computations, guards or protocol steps rather than API
operations (signals, risk checks, debate rounds, device commands...). This
module never drops one:

* an action that duplicates a served operation is covered by that operation's
  tool: its name is a client method, its dispatch branch returns one served
  operation's result unchanged (wrapping and side effects aside), its entry in
  a module-level action table names served operations, or its split name is
  already a served tool name;
* every other action becomes ``<tool>_<action>``, with the parameters that
  action's dispatch branch reads (all of them when the branch cannot be
  located), no ``action`` argument, and read-only/destructive hints from the
  action's verb;
* a tool whose actions cannot be enumerated is kept as is, with a warning.

Every decision is recorded in the server's registration report
(:func:`action_split_report`): one :class:`SplitDecision` per action, naming the
tool that serves it. A covered action is logged at debug level, never raised.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Collection, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from scion_sdk.mcp._action_clients import _dispatched_client
from scion_sdk.mcp._action_coverage import _Context, _coverage
from scion_sdk.mcp._action_enumerate import _branches, _names, tool_actions
from scion_sdk.mcp._action_literals import _literal_tables
from scion_sdk.mcp._action_signature import _per_action
from scion_sdk.mcp._action_tables import _action_tables
from scion_sdk.mcp._action_verbs import _annotations, _is_read_verb

logger = logging.getLogger(__name__)

__all__ = [
    "SPLIT_ACTION_TAG",
    "SplitDecision",
    "action_split_report",
    "assert_tools_classified",
    "split_action_tool",
    "split_tool_classes",
    "tool_actions",
    "unclassified_tools",
]

#: Tag on every tool produced by splitting an action-routed tool.
SPLIT_ACTION_TAG = "split-action"
#: Server attribute holding the registration report (``list[SplitDecision]``).
_SPLIT_REPORT_ATTRIBUTE = "_action_split_report"


@dataclass(frozen=True)
class SplitDecision:
    """How one action of an action-routed tool is served.

    ``outcome`` is ``split`` (``served_by`` is the new ``<tool>_<action>``
    tool), ``covered`` (``served_by`` is the per-operation tool that serves the
    same call; ``split`` is the name that was not registered) or ``kept`` (the
    whole tool stays because its actions cannot be enumerated). ``reason``
    says why an action is covered: ``name``, ``operation``, ``table`` or
    ``dispatch`` (a generic router over one served client). A kept router
    records ``actions_unenumerable``.
    """

    tool: str
    action: str
    split: str
    outcome: str
    served_by: str
    reason: str = ""


def action_split_report(mcp: Any) -> list[dict[str, str]]:
    """Every split decision made on ``mcp``, as plain dictionaries."""
    return [asdict(item) for item in getattr(mcp, _SPLIT_REPORT_ATTRIBUTE, [])]


def _record(mcp: Any, decision: SplitDecision) -> None:
    report: list[SplitDecision] = getattr(mcp, _SPLIT_REPORT_ATTRIBUTE, [])
    report.append(decision)
    setattr(mcp, _SPLIT_REPORT_ATTRIBUTE, report)
    if decision.outcome == "covered":
        logger.debug(
            "split tool %r not registered: action %r of %r is served by %r (%s)",
            decision.split,
            decision.action,
            decision.tool,
            decision.served_by,
            decision.reason,
        )


def _register_split(mcp: Any, ctx: _Context, tool: Any, *, action: str) -> str:
    branch = ctx.branches.get(action)
    params = set(inspect.signature(tool.fn).parameters)
    keep = (_names(branch) & params) if branch is not None else None
    fn, _served = _per_action(tool, action, keep)
    tool_name = f"{ctx.prefix}_{action}"
    mcp.tool(
        name=tool_name,
        description=f"{action.replace('_', ' ').capitalize()} ({ctx.name}). "
        + (tool.description or ""),
        tags=set(tool.tags or set()) | {SPLIT_ACTION_TAG},
        annotations=_annotations(action, tool.annotations),
    )(fn)
    return tool_name


def _record_dispatched(
    mcp: Any, name: str, *, prefix: str, dispatched: Mapping[str, str]
) -> None:
    for method, served_by in dispatched.items():
        split = f"{prefix}_{method}"
        decision = SplitDecision(name, method, split, "covered", served_by, "dispatch")
        _record(mcp, decision)


def _keep_unsplit(mcp: Any, name: str) -> list[str]:
    logger.warning(
        "action-routed tool %r kept unsplit: its actions could not be enumerated",
        name,
    )
    _record(mcp, SplitDecision(name, "", name, "kept", name, "actions_unenumerable"))
    return [name]


def _split_actions(
    mcp: Any, ctx: _Context, tool: Any, *, actions: list[str]
) -> list[str]:
    added: list[str] = []
    for action in actions:
        split = f"{ctx.prefix}_{action}"
        covered = _coverage(action, ctx)
        if covered is not None:
            _record(mcp, SplitDecision(ctx.name, action, split, "covered", *covered))
            continue
        added.append(_register_split(mcp, ctx, tool, action=action))
        _record(mcp, SplitDecision(ctx.name, action, split, "split", split))
    return added


def split_action_tool(
    mcp: Any,
    name: str,
    tool: Any,
    *,
    operations: Mapping[str, str],
    taken: Collection[str] = (),
    clients: Mapping[Any, Mapping[str, str]] | None = None,
    prefix: str | None = None,
) -> list[str]:
    """Replace one action-routed tool by per-action tools; never lose an action.

    Each per-action tool is named ``<prefix>_<action>``; ``prefix`` defaults to
    the routed tool's own name.

    ``operations`` maps each client method served as an operation tool to that
    tool's name; ``taken`` holds every other tool name already served or about
    to be; ``clients`` maps each served client class and its factory to its operations,
    so a generic router over one client is covered by that client's tools.
    An action an operation tool already serves is not registered twice:
    the operation tool wins, and the decision is logged at debug level and
    recorded in :func:`action_split_report`. Returns the names of the tools
    added; an empty list means every action is covered. When the actions
    cannot be enumerated, the original tool stays registered and a warning is
    logged.
    """
    actions = tool_actions(tool)
    dispatched = None if actions else _dispatched_client(tool.fn, clients or {})
    if dispatched:
        mcp.local_provider.remove_tool(name)
        _record_dispatched(mcp, name, prefix=prefix or name, dispatched=dispatched)
        return []
    if not actions:
        return _keep_unsplit(mcp, name)
    ctx = _Context(
        name,
        prefix or name,
        operations,
        set(taken) | set(operations.values()),
        _branches(tool.fn),
        _action_tables(tool.fn, actions),
        _literal_tables(tool.fn),
    )
    mcp.local_provider.remove_tool(name)
    return _split_actions(mcp, ctx, tool, actions=actions)


def split_tool_classes(
    mcp: Any,
    declared: Mapping[str, str | Mapping[str, str]],
    *,
    read_classes: Collection[str] = (),
) -> dict[str, str]:
    """Risk class of every split ``<tool>_<action>`` tool that can be derived.

    ``declared`` maps a tool name to its class (one string for the whole tool)
    or to a per-action mapping. A split tool takes its own action's declared
    class first, then its parent's single class. A parent class listed in
    ``read_classes`` is inherited only by an action with a recognized read verb that
    contains no recognized mutation verb. A mutating or unrecognized action is
    left unclassified; a parent read-only hint does not override this check.
    A split tool with no declared parent is left out too.
    """
    reads = frozenset(read_classes)
    classes: dict[str, str] = {}
    for item in getattr(mcp, _SPLIT_REPORT_ATTRIBUTE, []):
        if item.outcome != "split" or item.tool not in declared:
            continue
        parent = declared[item.tool]
        if not isinstance(parent, str):
            if item.action in parent:
                classes[item.split] = parent[item.action]
            continue
        if parent in reads and not _is_read_verb(item.action):
            continue
        classes[item.split] = parent
    return classes


def unclassified_tools(
    mcp: Any,
    classified: Collection[str],
    declared: Mapping[str, str | Mapping[str, str]] | None = None,
    *,
    read_classes: Collection[str] = (),
) -> list[str]:
    """Registered tool names with no class, counting inherited split classes."""
    known = set(classified)
    known |= set(split_tool_classes(mcp, declared or {}, read_classes=read_classes))
    return sorted(
        {
            str(getattr(component, "name", "") or "")
            for key, component in mcp.local_provider._components.items()
            if str(key).startswith("tool:") and getattr(component, "name", None)
        }
        - known
    )


def assert_tools_classified(
    mcp: Any,
    classified: Collection[str],
    declared: Mapping[str, str | Mapping[str, str]] | None = None,
    *,
    read_classes: Collection[str] = (),
) -> None:
    """Refuse startup when a registered tool has no class; fail closed.

    ``classified`` lists tools classified by name. A split tool is classified
    by inheritance from ``declared`` (see :func:`split_tool_classes`); anything
    else unknown raises, so an unknown tool is never treated as read-only.
    """
    missing = unclassified_tools(mcp, classified, declared, read_classes=read_classes)
    if missing:
        raise RuntimeError(
            "Unclassified MCP tools prevent startup: " + ", ".join(missing)
        )
