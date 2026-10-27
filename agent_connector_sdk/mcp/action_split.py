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

import ast
import inspect
import logging
import re
import textwrap
import typing
from collections.abc import Callable, Collection, Iterator, Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal, get_args, get_origin

from pydantic.fields import FieldInfo

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
#: Server attribute holding the names of parents declared read-only (``set[str]``).
_READ_ONLY_PARENTS_ATTRIBUTE = "_action_split_read_only_parents"
#: Calls that adapt how an operation runs or is returned, never what it computes.
_ADAPTERS = frozenset(
    {
        "run_blocking",
        "partial",
        "to_thread",
        "_invoke",
        "invoke",
        "dict",
        "list",
        "tuple",
        "str",
        "int",
        "float",
        "bool",
        "len",
        "min",
        "max",
        "sorted",
        "isinstance",
        "jsonable_result",
        "dumps",
        "loads",
    }
)


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
_LISTED = re.compile(
    r"one of:\s*([a-z][a-z0-9_]*(?:\s*,\s*(?:or\s+)?[a-z][a-z0-9_]*)+)", re.IGNORECASE
)
_LISTED_NAME = re.compile(r"[a-z][a-z0-9_]*")
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
    found += _described_actions(str(prop.get("description", "")))
    seen: list[str] = []
    for name in found:
        if name not in seen and name not in _DISCOVERY:
            seen.append(name)
    return seen


def _described_actions(description: str) -> list[str]:
    """Actions an ``action`` description lists: quoted names, else ``One of: a, b``."""
    quoted = _QUOTED.findall(description)
    if quoted:
        return list(quoted)
    match = _LISTED.search(description)
    if match is None:
        return []
    return [name for name in _LISTED_NAME.findall(match.group(1)) if name != "or"]


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


def _cell_strings(value: Any) -> Iterator[str]:
    """String constants an action-table entry names (directly or in a closure)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, tuple | list):
        for item in value:
            yield from _cell_strings(item)
    elif callable(value):
        for cell in getattr(value, "__closure__", None) or ():
            try:
                yield from _cell_strings(cell.cell_contents)
            except ValueError:
                continue
        for arg in getattr(value, "args", ()):
            yield from _cell_strings(arg)


def _action_tables(fn: Callable[..., Any], actions: list[str]) -> list[dict[str, Any]]:
    """``{action: method}`` tables the tool body refers to (globals or closure)."""
    target = inspect.unwrap(fn)
    tree = _function_body(target)
    owners = [target] + (_delegates(target, tree) if tree is not None else [])
    candidates = [
        getattr(owner, "__globals__", {}).get(name)
        for owner in owners
        for name in getattr(getattr(owner, "__code__", None), "co_names", ())
    ]
    for cell in getattr(target, "__closure__", None) or ():
        try:
            candidates.append(cell.cell_contents)
        except ValueError:
            continue
    return [
        table
        for table in candidates
        if isinstance(table, dict)
        and table
        and all(isinstance(key, str) for key in table)
        and set(actions) & set(table)
    ]


def _table_operations(
    tables: list[dict[str, Any]], action: str, operations: Mapping[str, str]
) -> list[str]:
    """Served operations a table entry dispatches ``action`` to.

    An entry is a method name, a selector closing over method names, or a
    handler function whose body returns one served operation unchanged.
    """
    for table in tables:
        if action not in table:
            continue
        entry = table[action]
        handler = _branch_operation(_function_body(entry), operations)
        if handler is None:
            handler = _lambda_operation(entry, operations)
        if handler is not None:
            return [handler]
        if not hasattr(entry, "__code__") or getattr(entry, "__closure__", None):
            return [m for m in _cell_strings(entry) if m in operations]
    return []


def _delegates(fn: Callable[..., Any], tree: ast.AST) -> list[Any]:
    """Module functions ``fn`` hands its ``action`` to (``h(..., action, ...)``)."""
    scope = getattr(inspect.unwrap(fn), "__globals__", {})
    found: list[Any] = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        args = [call.func, *call.args, *(k.value for k in call.keywords)]
        if not any(isinstance(a, ast.Name) and a.id == "action" for a in args):
            continue
        for arg in args:
            target = scope.get(arg.id) if isinstance(arg, ast.Name) else None
            if inspect.isfunction(target) and target is not fn:
                found.append(target)
    return found


def _literal_tables(fn: Callable[..., Any]) -> dict[str, ast.AST]:
    """``{action: entry}`` from dict literals in ``fn`` or a function it delegates to.

    A dict literal whose keys are all strings, such as
    ``{"get_settings": client.get_org_settings, ...}``, is an action table.
    """
    tree = _function_body(fn)
    if tree is None:
        return {}
    trees = [tree] + [t for d in _delegates(fn, tree) if (t := _function_body(d))]
    out: dict[str, ast.AST] = {}
    for node in (n for t in trees for n in ast.walk(t)):
        if not isinstance(node, ast.Dict) or not node.keys:
            continue
        keys = [k.value if isinstance(k, ast.Constant) else None for k in node.keys]
        if all(isinstance(k, str) for k in keys):
            for key, value in zip(keys, node.values, strict=True):
                out.setdefault(str(key), value)
    return out


def _literal_operation(
    entries: dict[str, ast.AST], action: str, operations: Mapping[str, str]
) -> str | None:
    """The one served operation a literal table entry references."""
    entry = entries.get(action)
    refs = _operation_refs(entry, operations) if entry is not None else set()
    return refs.pop() if len(refs) == 1 else None


def _assigned(statement: ast.stmt) -> set[str]:
    targets: list[ast.AST] = []
    if isinstance(statement, ast.Assign):
        targets = list(statement.targets)
    elif isinstance(statement, ast.AnnAssign | ast.AugAssign):
        targets = [statement.target]
    return {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}


def _operation_refs(node: ast.AST, operations: Mapping[str, str]) -> set[str]:
    """Served operation names referenced as ``<obj>.<operation>`` in ``node``."""
    return {
        n.attr
        for n in ast.walk(node)
        if isinstance(n, ast.Attribute) and n.attr in operations
    }


def _transforms(
    node: ast.AST, tainted: set[str], operations: Mapping[str, str]
) -> bool:
    """Whether ``node`` feeds operation data through a computing function call."""
    for call in ast.walk(node):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
            continue
        if call.func.id in _ADAPTERS:
            continue
        args = [*call.args, *(k.value for k in call.keywords)]
        if any(_operation_refs(a, operations) or _names(a) & tainted for a in args):
            return True
    return False


def _taint(statements: list[ast.stmt], operations: Mapping[str, str]) -> set[str]:
    """Names that hold operation data, propagated to a fixed point."""
    tainted: set[str] = set()
    while True:
        grown = set(tainted)
        for statement in statements:
            value = getattr(statement, "value", None)
            if value is not None and (
                _operation_refs(value, operations) or _names(value) & grown
            ):
                grown |= _assigned(statement)
        if grown == tainted:
            return tainted
        tainted = grown


def _branch_operation(
    branch: ast.AST | None, operations: Mapping[str, str]
) -> str | None:
    """The one served operation a branch returns unchanged, if it does.

    The branch references exactly one served operation, and the value it
    returns is that operation's result, possibly wrapped by adapters,
    attribute calls (``.model_dump()``) or a literal envelope. A statement
    whose value is not returned (a progress note, a mirror write) is a side
    effect, not a computation. A branch that passes operation data through a
    computing function is a capability of its own.
    """
    if branch is None:
        return None
    refs = _operation_refs(branch, operations)
    if len(refs) != 1:
        return None
    statements = [n for n in ast.walk(branch) if isinstance(n, ast.stmt)]
    tainted = _taint(statements, operations)
    for statement in statements:
        value = getattr(statement, "value", None)
        flows = isinstance(statement, ast.Return) or bool(_assigned(statement))
        if value is not None and flows and _transforms(value, tainted, operations):
            return None
    return refs.pop()


def _lambda_operation(fn: Any, operations: Mapping[str, str]) -> str | None:
    """The one served operation a handler lambda calls, when it calls nothing else.

    A lambda's source cannot be parsed on its own, so its code object is read:
    it names exactly one served operation and no other module function.
    """
    code = getattr(fn, "__code__", None)
    if code is None or getattr(fn, "__name__", "") != "<lambda>":
        return None
    names = set(code.co_names)
    served = names & set(operations)
    scope = getattr(fn, "__globals__", {})
    computing = {
        name
        for name in names - served
        if callable(scope.get(name)) and name not in _ADAPTERS
    }
    return served.pop() if len(served) == 1 and not computing else None


def _returned_class(factory: Any) -> Any:
    """The class a client factory's return annotation names, or ``None``."""
    try:
        return typing.get_type_hints(factory).get("return")
    except Exception:
        return None


def _client_factories(fn: Any, tree: ast.AST) -> dict[str, list[Any]]:
    """``{variable: [factory, returned class]}`` for clients ``fn`` builds or injects."""
    scope = getattr(inspect.unwrap(fn), "__globals__", {})
    factories: dict[str, Any] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            factory = scope.get(func.id) if isinstance(func, ast.Name) else None
            for target in node.targets:
                if isinstance(target, ast.Name) and callable(factory):
                    factories[target.id] = factory
    for name, param in inspect.signature(fn).parameters.items():
        factory = getattr(param.default, "dependency", None)
        if callable(factory):
            factories[name] = factory
    return {name: [f, _returned_class(f)] for name, f in factories.items()}


def _dispatched_client(
    fn: Any, clients: Mapping[Any, Mapping[str, str]]
) -> Mapping[str, str] | None:
    """Operations of the one served client a generic router dispatches to.

    A router whose actions are any method of a client (``getattr(client,
    action)`` or ``dispatch(client, action, ...)``) serves exactly that
    client's operations, each already served as its own tool.
    """
    tree = _function_body(fn)
    if tree is None:
        return None
    factories = _client_factories(fn, tree)
    matches: list[Mapping[str, str]] = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        args = [*call.args, *(k.value for k in call.keywords)]
        names = {a.id for a in args if isinstance(a, ast.Name)}
        if "action" not in names:
            continue
        for name in names & set(factories):
            found = [clients[k] for k in factories[name] if _hashable_in(k, clients)]
            matches += [m for m in found[:1] if m not in matches]
    return matches[0] if len(matches) == 1 else None


def _hashable_in(key: Any, mapping: Mapping[Any, Any]) -> bool:
    try:
        return key is not None and key in mapping
    except TypeError:
        return False


def _function_body(fn: Any) -> ast.AST | None:
    source = _source(fn) if callable(fn) and hasattr(fn, "__code__") else ""
    try:
        return ast.parse(source) if source else None
    except SyntaxError:
        return None


@dataclass(frozen=True)
class _Context:
    name: str
    prefix: str
    operations: Mapping[str, str]
    taken: Collection[str]
    branches: dict[str, ast.AST]
    tables: list[dict[str, Any]]
    literals: dict[str, ast.AST]


def _coverage(action: str, ctx: _Context) -> tuple[str, str] | None:
    """``(serving_tool, reason)`` when an operation already serves ``action``."""
    split = f"{ctx.prefix}_{action}"
    if split in ctx.taken:
        return split, "name"
    if action in ctx.operations:
        return ctx.operations[action], "operation"
    method = _branch_operation(ctx.branches.get(action), ctx.operations)
    if method is not None:
        return ctx.operations[method], "operation"
    from_table = _table_operations(ctx.tables, action, ctx.operations)
    if from_table:
        return ctx.operations[from_table[0]], "table"
    literal = _literal_operation(ctx.literals, action, ctx.operations)
    if literal is not None:
        return ctx.operations[literal], "table"
    return None


def _register_split(mcp: Any, ctx: _Context, tool: Any, action: str) -> str:
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
        for method, served_by in dispatched.items():
            split = f"{prefix or name}_{method}"
            _record(
                mcp,
                SplitDecision(name, method, split, "covered", served_by, "dispatch"),
            )
        return []
    if not actions:
        logger.warning(
            "action-routed tool %r kept unsplit: its actions could not be enumerated",
            name,
        )
        _record(
            mcp, SplitDecision(name, "", name, "kept", name, "actions_unenumerable")
        )
        return [name]
    ctx = _Context(
        name,
        prefix or name,
        operations,
        set(taken) | set(operations.values()),
        _branches(tool.fn),
        _action_tables(tool.fn, actions),
        _literal_tables(tool.fn),
    )
    declared = tool.annotations
    if getattr(declared, "readOnlyHint", None) is True and not getattr(
        declared, "destructiveHint", None
    ):
        parents: set[str] = getattr(mcp, _READ_ONLY_PARENTS_ATTRIBUTE, set())
        parents.add(name)
        setattr(mcp, _READ_ONLY_PARENTS_ATTRIBUTE, parents)
    mcp.local_provider.remove_tool(name)
    added: list[str] = []
    for action in actions:
        split = f"{ctx.prefix}_{action}"
        covered = _coverage(action, ctx)
        if covered is not None:
            _record(mcp, SplitDecision(name, action, split, "covered", *covered))
            continue
        added.append(_register_split(mcp, ctx, tool, action))
        _record(mcp, SplitDecision(name, action, split, "split", split))
    return added


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
    ``read_classes`` is inherited only by an action whose verb reads, or by any
    action of a parent that declared ``readOnlyHint`` itself: a
    mutating or unrecognised action of any other parent is left out, so it stays unclassified and
    can never become read-only by inheritance. A split tool with no declared
    parent is left out too.
    """
    reads = frozenset(read_classes)
    read_parents: set[str] = getattr(mcp, _READ_ONLY_PARENTS_ATTRIBUTE, set())
    classes: dict[str, str] = {}
    for item in getattr(mcp, _SPLIT_REPORT_ATTRIBUTE, []):
        if item.outcome != "split" or item.tool not in declared:
            continue
        parent = declared[item.tool]
        if not isinstance(parent, str):
            if item.action in parent:
                classes[item.split] = parent[item.action]
            continue
        verb_reads = bool(_READ_ONLY.search(item.action)) and not _DESTRUCTIVE.search(
            item.action
        )
        if parent in reads and not (verb_reads or item.tool in read_parents):
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
