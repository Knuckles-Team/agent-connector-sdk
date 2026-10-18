"""Split hand-written action-routed tools into one typed tool per action.

A registrar tool that takes an ``action`` argument used to be dropped as soon as
per-operation client tools registered. That silently removed every hand-written
tool whose actions were computations, guards or protocol steps rather than API
operations (signals, risk checks, debate rounds, device commands...). This
module never drops one:

* an action that duplicates a served operation (its name is a client method,
  or its dispatch branch calls one) is covered by that operation's tool;
* every other action becomes ``<tool>_<action>``, with the parameters that
  action's dispatch branch reads (all of them when the branch cannot be
  located), no ``action`` argument, and read-only/destructive hints from the
  action's verb;
* a tool whose actions cannot be enumerated is kept as is, with a warning.
"""

from __future__ import annotations

import ast
import inspect
import logging
import re
import textwrap
import typing
from collections.abc import Callable, Iterable
from typing import Any, Literal, get_args, get_origin

from pydantic.fields import FieldInfo

logger = logging.getLogger(__name__)

__all__ = ["SPLIT_ACTION_TAG", "split_action_tool", "tool_actions"]

#: Tag on every tool produced by splitting an action-routed tool.
SPLIT_ACTION_TAG = "split-action"

_READ_ONLY = re.compile(
    r"(^|_)(list|get|read|show|status|describe|inspect|info|query|search|find|fetch|"
    r"check|validate|verify|scan|audit|analy[sz]e|calculate|compute|estimate|"
    r"preview|explain|view|count|history|stats?|metrics|export|diff|compare|"
    r"health|ping|test|detect|lookup|resolve|evaluate|discover|whoami|limits)(_|$)"
)
_DESTRUCTIVE = re.compile(
    r"(^|_)(delete|remove|destroy|drop|purge|wipe|erase|truncate|kill|terminate|"
    r"cancel|revoke|rotate|reset|uninstall|prune|halt|clear)(_|$)"
)
_COMPARE = re.compile(r"""\baction\s*==\s*["']([a-z][a-z0-9_]*)["']""")
_QUOTED = re.compile(r"'([a-z][a-z0-9_]*)'")
_DISCOVERY = frozenset({"list_actions", "help", "actions"})


def _source(fn: Callable[..., Any]) -> str:
    try:
        return textwrap.dedent(inspect.getsource(inspect.unwrap(fn)))
    except (OSError, TypeError):
        return ""


def tool_actions(tool: Any) -> list[str]:
    """Every action an action-routed tool implements, in declaration order."""
    fn = getattr(tool, "fn", None)
    hints: dict[str, Any] = {}
    if fn is not None:
        try:
            hints = typing.get_type_hints(fn, include_extras=True)
        except Exception:
            hints = {}
    found: list[str] = []
    annotation = hints.get("action")
    if get_origin(annotation) is typing.Annotated:
        annotation = get_args(annotation)[0]
    if get_origin(annotation) is Literal:
        found += [str(item) for item in get_args(annotation)]
    prop = (
        (getattr(tool, "parameters", None) or {})
        .get("properties", {})
        .get("action", {})
    )
    found += [str(item) for item in prop.get("enum") or []]
    if fn is not None:
        found += _COMPARE.findall(_source(fn))
    found += _QUOTED.findall(str(prop.get("description", "")))
    seen: list[str] = []
    for name in found:
        if name not in seen and name not in _DISCOVERY:
            seen.append(name)
    return seen


def _branches(fn: Callable[..., Any]) -> dict[str, ast.AST]:
    """Map each ``action == "x"`` test in ``fn`` to the branch it guards."""
    source = _source(fn)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    out: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "action"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and isinstance(test.comparators[0], ast.Constant)
            and isinstance(test.comparators[0].value, str)
        ):
            out.setdefault(
                test.comparators[0].value, ast.Module(body=node.body, type_ignores=[])
            )
    return out


def _names(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _annotations(action: str, declared: Any) -> dict[str, Any]:
    destructive = bool(_DESTRUCTIVE.search(action))
    read_only = bool(_READ_ONLY.search(action)) and not destructive
    return {
        "title": action.replace("_", " ").title(),
        "readOnlyHint": read_only,
        "destructiveHint": destructive,
        "idempotentHint": read_only or destructive,
        "openWorldHint": getattr(declared, "openWorldHint", None)
        if getattr(declared, "openWorldHint", None) is not None
        else True,
    }


def _plain_default(param: inspect.Parameter) -> Any:
    default = param.default
    if isinstance(default, FieldInfo):
        if default.default_factory is not None:
            return default.default_factory()  # type: ignore[call-arg]
        return None if default.is_required() else default.default
    return None if default is inspect.Parameter.empty else default


def _per_action(
    tool: Any, action: str, keep: set[str] | None
) -> tuple[Callable[..., Any], list[str]]:
    fn = tool.fn
    signature = inspect.signature(fn)
    try:
        hints = typing.get_type_hints(fn, include_extras=True)
    except Exception:
        hints = dict(getattr(fn, "__annotations__", {}))
    served: list[inspect.Parameter] = []
    omitted: dict[str, Any] = {}
    for param in signature.parameters.values():
        if param.name == "action":
            continue
        is_context = "Context" in str(hints.get(param.name, param.annotation))
        if keep is None or param.name in keep or is_context:
            served.append(
                param.replace(annotation=hints.get(param.name, param.annotation))
            )
        else:
            omitted[param.name] = _plain_default(param)

    async def call(**kwargs: Any) -> Any:
        result = fn(action=action, **omitted, **kwargs)
        return await result if inspect.isawaitable(result) else result

    call.__signature__ = signature.replace(  # type: ignore[attr-defined]
        parameters=served,
        return_annotation=hints.get("return", signature.return_annotation),
    )
    call.__annotations__ = {
        k: v for k, v in hints.items() if k == "return" or k in {p.name for p in served}
    }
    call.__name__ = action
    call.__doc__ = fn.__doc__
    return call, [p.name for p in served]


def split_action_tool(
    mcp: Any,
    name: str,
    tool: Any,
    *,
    operations: Iterable[str],
) -> list[str]:
    """Replace one action-routed tool by per-action tools; never lose an action.

    ``operations`` are the client method names served as operation tools. An
    action covered by one of them is not served twice. Returns the names of the
    tools added; an empty list means every action is covered. When the actions
    cannot be enumerated, the original tool stays registered and a warning is
    logged.
    """
    actions = tool_actions(tool)
    if not actions:
        logger.warning(
            "action-routed tool %r kept unsplit: its actions could not be enumerated",
            name,
        )
        return [name]
    covered_ops = set(operations)
    branches = _branches(tool.fn)
    params = set(inspect.signature(tool.fn).parameters)
    added: list[str] = []
    mcp.local_provider.remove_tool(name)
    for action in actions:
        branch = branches.get(action)
        if action in covered_ops or _is_pass_through(branch, covered_ops):
            continue
        keep = (_names(branch) & params) if branch is not None else None
        fn, _served = _per_action(tool, action, keep)
        tool_name = f"{name}_{action}"
        mcp.tool(
            name=tool_name,
            description=f"{action.replace('_', ' ').capitalize()} ({name}). "
            + (tool.description or ""),
            tags=set(tool.tags or set()) | {SPLIT_ACTION_TAG},
            annotations=_annotations(action, tool.annotations),
        )(fn)
        added.append(tool_name)
    return added


def _is_pass_through(branch: ast.AST | None, operations: set[str]) -> bool:
    """Whether a branch only returns one served operation's result.

    ``return client.op(...)``, optionally wrapped in a serializer call such as
    ``json.dumps(...)``: the operation tool already serves it. Any branch that
    computes, guards or combines is a capability of its own.
    """
    if branch is None or len(getattr(branch, "body", [])) != 1:
        return False
    statement = branch.body[0]  # type: ignore[attr-defined]
    if not isinstance(statement, ast.Return) or statement.value is None:
        return False
    calls = [n for n in ast.walk(statement.value) if isinstance(n, ast.Call)]
    ops = [
        c
        for c in calls
        if isinstance(c.func, ast.Attribute) and c.func.attr in operations
    ]
    return len(ops) == 1 and len(calls) <= 2
