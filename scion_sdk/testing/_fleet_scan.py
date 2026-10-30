"""Fail-closed source traversal and the legacy-import predicate for the fleet scan."""

from __future__ import annotations

import ast

_IMPORT_MODULES = {"importlib", "builtins"}
_IMPORT_FUNCTIONS = {"import_module", "__import__"}


def _import_spellings(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Return the names bound to the import functions and to their modules."""
    import_functions = {"__import__"}
    module_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            module_aliases.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name in _IMPORT_MODULES
            )
        elif isinstance(node, ast.ImportFrom) and node.module in _IMPORT_MODULES:
            import_functions.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name in _IMPORT_FUNCTIONS
            )
    return import_functions, module_aliases


def _static_import_is_legacy(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(
            alias.name.split(".")[0] == "agent_utilities" for alias in node.names
        )
    if isinstance(node, ast.ImportFrom):
        return (node.module or "").split(".")[0] == "agent_utilities"
    return False


def _is_dynamic_import(
    node: ast.Call, import_functions: set[str], module_aliases: set[str]
) -> bool:
    function = node.func
    if isinstance(function, ast.Name):
        return function.id in import_functions
    return (
        isinstance(function, ast.Attribute)
        and isinstance(function.value, ast.Name)
        and function.value.id in module_aliases
        and function.attr in _IMPORT_FUNCTIONS
    )


def _dynamic_import_verdict(node: ast.Call) -> bool | None:
    """True for a legacy module, None when the target cannot be proven."""
    if not node.args or not isinstance(node.args[0], ast.Constant):
        return None
    module = node.args[0].value
    if not isinstance(module, str) or module.startswith("."):
        return None
    return module.split(".")[0] == "agent_utilities"


def _imports_agent_utilities(source: str) -> bool | None:
    tree = ast.parse(source)
    import_functions, module_aliases = _import_spellings(tree)
    uncertain = False
    for node in ast.walk(tree):
        if _static_import_is_legacy(node):
            return True
        if not isinstance(node, ast.Call):
            continue
        if not _is_dynamic_import(node, import_functions, module_aliases):
            continue
        verdict = _dynamic_import_verdict(node)
        if verdict:
            return True
        uncertain |= verdict is None
    return None if uncertain else False
