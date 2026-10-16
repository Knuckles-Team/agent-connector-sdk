"""Check a connector's declared env vars against the vars its code reads (SDK-CONNECTOR-CONTROL-R014.14).

Replaces ``agent_utilities.mcp.check_env_var_drift`` for connectors. The code
is the authority on which variables exist. A connector declares them in
``.env.example``, in every ``mcp_config*.json`` ``env`` block, and in
``docker/*compose*.yml`` ``environment:`` blocks. This module diffs those
declarations against the code-read set:

- ``DEAD``: declared, but no code reads it. Remove it.
- ``UNDOCUMENTED``: the package code reads it, but ``.env.example`` lacks it. Add it.

The code-read set is the package's literal reads (``setting``/``getenv``/
``os.environ.get``/``os.environ[...]``, ``Field(alias="VAR")``, a
``enable_flag = "VAR"`` attribute, a same-module ``NAME = "VAR"`` constant
passed to a reader), the ``register_<tag>_tools`` toggles (``<TAG>TOOL``),
compose ``image``/``command``/``entrypoint``/``args`` substitutions, and the
names a declared dynamic family composes (a function publishing
``func.dynamic_env_prefix_arg`` and ``func.dynamic_env_suffixes``). The
package's ``scripts/`` reads and the SDK's own reads only suppress ``DEAD``;
they never require an ``.env.example`` entry.

Usage, from a connector root::

    python -m agent_connector_sdk.mcp.env_drift            # report
    python -m agent_connector_sdk.mcp.env_drift --check    # exit 1 on drift
    python -m agent_connector_sdk.mcp.env_drift --json     # machine-readable
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "FRAMEWORK_ENV",
    "RUNTIME_ALLOWLIST",
    "analyze",
    "format_report",
    "framework_dynamic_families",
    "framework_reads",
    "main",
]

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_ENV_DECL = re.compile(r"^\s*#?\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=")
_REGISTRAR = re.compile(r"(?<![0-9A-Za-z_])register_([a-z][a-z0-9_]*?)_tools\b")
_SUBST = re.compile(r"\$\{([^}]*)\}")

#: Variables the SDK server runtime reads on every connector's behalf.
FRAMEWORK_ENV: frozenset[str] = frozenset(
    {
        "TRANSPORT",
        "HOST",
        "PORT",
        "DEBUG",
        "AUTH_TYPE",
        "MCP_URL",
        "MCP_ENABLED_TOOLS",
        "MCP_DISABLED_TOOLS",
        "MCP_ENABLED_TAGS",
        "MCP_DISABLED_TAGS",
        "MCP_CLIENT_AUTH",
        "MCP_BASIC_AUTH_USERNAME",
        "MCP_BASIC_AUTH_PASSWORD_REF",
        "OIDC_CLIENT_ID",
        "OIDC_CLIENT_SECRET_REF",
        "EUNOMIA_TYPE",
        "EUNOMIA_POLICY_FILE",
        "EUNOMIA_REMOTE_URL",
        "ENABLE_OTEL",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_PROTOCOL",
        "OTEL_EXPORTER_OTLP_HEADERS",
        "OTEL_EXPORTER_OTLP_HEADERS_REF",
        "OTEL_EXPORTER_OTLP_PUBLIC_KEY_REF",
        "OTEL_EXPORTER_OTLP_SECRET_KEY_REF",
        "OTEL_TLS_PROFILE",
        "OTEL_TLS_PROFILE_REF",
    }
)

#: Process and library variables set in a launch env, never connector config.
RUNTIME_ALLOWLIST: frozenset[str] = frozenset(
    {
        "TERM", "NO_COLOR", "FORCE_COLOR", "PYTHONUNBUFFERED",
        "PYTHONDONTWRITEBYTECODE", "PYTHONPATH", "LOG_LEVEL", "TZ", "PATH",
        "HOME", "USER", "SHELL", "PWD", "TMPDIR", "LANG", "LC_ALL", "DISPLAY",
        "WAYLAND_DISPLAY", "TMUX", "VIRTUAL_ENV", "APPDATA", "LOCALAPPDATA",
        "SYSTEMROOT", "PROGRAMFILES", "USERDOMAIN", "USERNAME",
        "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
        "XDG_RUNTIME_DIR", "SSH_AUTH_SOCK", "SSH_AGENT_PID", "CI",
        "PYTEST_CURRENT_TEST", "HF_HOME",
    }
)  # fmt: skip
_RUNTIME_PREFIXES: tuple[str, ...] = ("FASTMCP_",)
_WALK_SKIP_DIRS = frozenset(
    {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".venv",
     "__pycache__", "build", "dist", "node_modules"}
)  # fmt: skip
_NON_RUNTIME_SOURCE_DIRS = frozenset(
    {"docs", "examples", "reports", "scripts", "test", "tests"}
)
#: This module spells reader calls in prose; never scan it as a reader.
_SELF_DOC_FILES = frozenset({"env_drift.py", "check_env_var_drift.py"})
_COMPOSE_SUBST_KEYS = frozenset({"image", "command", "entrypoint", "args"})
_DYNAMIC_ENV_PREFIX_ATTR = "dynamic_env_prefix_arg"
_DYNAMIC_ENV_SUFFIXES_ATTR = "dynamic_env_suffixes"
#: function name -> (prefix parameter, its position or None, suffixes)
_DynamicFamily = tuple[str, "int | None", tuple[str, ...]]


def _walk_files(root: Path, *, suffix: str) -> list[Path]:
    """Source files under ``root``, pruning dependency and cache trees."""
    found: list[Path] = []
    for directory, names, files in os.walk(root):
        names[:] = sorted(
            n for n in names if n not in _WALK_SKIP_DIRS and not n.startswith(".")
        )
        found.extend(Path(directory) / n for n in files if n.endswith(suffix))
    return sorted(found)


def _skip_runtime_file(root: Path, py: Path) -> bool:
    try:
        parts = py.relative_to(root).parts
    except ValueError:
        parts = py.parts
    if any(part in _NON_RUNTIME_SOURCE_DIRS for part in parts[:-1]):
        return True
    return py.name in _SELF_DOC_FILES


def _parse(py: Path) -> ast.AST | None:
    try:
        return ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return None


def _literal_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _literal_env_name(node: ast.AST | None) -> str | None:
    value = _literal_str(node)
    return value if value and _ENV_NAME.fullmatch(value) else None


def _is_environ(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "environ"
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
        and node.attr == "environ"
    )


def _is_env_reader_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in {"_setting", "setting", "getenv"}
    if isinstance(func, ast.Attribute):
        if func.attr == "getenv":
            return isinstance(func.value, ast.Name) and func.value.id == "os"
        return func.attr == "get" and _is_environ(func.value)
    return False


def _is_field_call(node: ast.Call) -> bool:
    func = node.func
    return (isinstance(func, ast.Name) and func.id == "Field") or (
        isinstance(func, ast.Attribute) and func.attr == "Field"
    )


def _alias_literals(tree: ast.AST) -> dict[str, str]:
    """``NAME = "VAR"`` constants a reader may be passed instead of a literal."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        name = _literal_env_name(value)
        if not name:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                out[target.id] = name
            elif isinstance(target, ast.Attribute):
                out[target.attr] = name
    return out


def _env_names_from_tree(tree: ast.AST) -> set[str]:
    """Literal configuration reads in one parsed module (writes excluded)."""
    aliases = _alias_literals(tree)

    def name_of(node: ast.AST | None) -> str | None:
        literal = _literal_env_name(node)
        if literal:
            return literal
        if isinstance(node, ast.Name):
            return aliases.get(node.id)
        if isinstance(node, ast.Attribute):
            return aliases.get(node.attr)
        return None

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if (
                _is_env_reader_call(node)
                and node.args
                and (name := name_of(node.args[0]))
            ):
                found.add(name)
            if _is_field_call(node):
                for keyword in node.keywords:
                    if keyword.arg == "alias" and (
                        name := _literal_env_name(keyword.value)
                    ):
                        found.add(name)
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Load)
            and _is_environ(node.value)
        ):
            if name := name_of(node.slice):
                found.add(name)
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(
                (isinstance(t, ast.Name) and t.id == "enable_flag")
                or (isinstance(t, ast.Attribute) and t.attr == "enable_flag")
                for t in targets
            ) and (name := _literal_env_name(node.value)):
                found.add(name)
    return found


def _scan_setting_calls(root: Path) -> set[str]:
    """Every literal env read in runtime ``*.py`` under ``root``."""
    found: set[str] = set()
    for py in _walk_files(root, suffix=".py"):
        if _skip_runtime_file(root, py):
            continue
        tree = _parse(py)
        if tree is not None:
            found.update(_env_names_from_tree(tree))
    return found


def _script_reads(root: Path) -> set[str]:
    """Reads in the package's own ``scripts/``: suppress DEAD, never UNDOCUMENTED."""
    scripts = root / "scripts"
    return _scan_setting_calls(scripts) if scripts.is_dir() else set()


def _derive_toggle_vars(root: Path) -> set[str]:
    """``register_<tag>_tools`` in production code -> ``<TAG>TOOL``."""
    tags: set[str] = set()
    for py in _walk_files(root, suffix=".py"):
        if "tests" in py.parts or "test" in py.parts:
            continue
        try:
            tags.update(_REGISTRAR.findall(py.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
    tags -= {"verbose", "tool_surface", "conditional"}
    return {f"{tag.upper()}TOOL" for tag in tags}


def _dynamic_prefix(literal: str) -> str:
    return "".join(
        ch if ch.isalnum() else "_" for ch in str(literal or "").strip().upper()
    ).strip("_")


def _string_tuples(tree: ast.AST) -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not isinstance(value, ast.Tuple | ast.List):
            continue
        strings = [_literal_str(e) for e in value.elts]
        if not strings or any(s is None for s in strings):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                out[target.id] = tuple(s for s in strings if s is not None)
    return out


def _families_in_tree(tree: ast.AST) -> dict[str, _DynamicFamily]:
    named = _string_tuples(tree)
    params: dict[str, list[str]] = {}
    prefix_args: dict[str, str] = {}
    suffixes: dict[str, tuple[str, ...]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            params[node.name] = [a.arg for a in node.args.posonlyargs] + [
                a.arg for a in node.args.args
            ]
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not (
                isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
            ):
                continue
            func = target.value.id
            if target.attr == _DYNAMIC_ENV_PREFIX_ATTR:
                if literal := _literal_str(node.value):
                    prefix_args[func] = literal
            elif target.attr == _DYNAMIC_ENV_SUFFIXES_ATTR:
                value = node.value
                if isinstance(value, ast.Name) and value.id in named:
                    suffixes[func] = named[value.id]
                elif isinstance(value, ast.Tuple | ast.List):
                    found = [s for e in value.elts if (s := _literal_str(e))]
                    if found:
                        suffixes[func] = tuple(found)
    families: dict[str, _DynamicFamily] = {}
    for func, prefix_arg in prefix_args.items():
        if func in suffixes:
            order = params.get(func, [])
            position = order.index(prefix_arg) if prefix_arg in order else None
            families[func] = (prefix_arg, position, suffixes[func])
    return families


def _scan_dynamic_families(root: Path) -> dict[str, _DynamicFamily]:
    """Every dynamic-family declaration in runtime code under ``root``."""
    families: dict[str, _DynamicFamily] = {}
    for py in _walk_files(root, suffix=".py"):
        if _skip_runtime_file(root, py):
            continue
        tree = _parse(py)
        if tree is not None:
            families.update(_families_in_tree(tree))
    return families


def _family_reads_for_call(
    node: ast.Call, families: dict[str, _DynamicFamily]
) -> set[str]:
    func = node.func
    name = (
        func.id
        if isinstance(func, ast.Name)
        else func.attr
        if isinstance(func, ast.Attribute)
        else None
    )
    family = families.get(name) if name else None
    if family is None:
        return set()
    prefix_arg, position, suffixes = family
    literal = next(
        (_literal_str(k.value) for k in node.keywords if k.arg == prefix_arg), None
    )
    if literal is None and position is not None and len(node.args) > position:
        literal = _literal_str(node.args[position])
    prefix = _dynamic_prefix(literal) if literal else ""
    return {f"{prefix}_{suffix}" for suffix in suffixes} if prefix else set()


def _scan_dynamic_family_reads(
    root: Path, families: dict[str, _DynamicFamily]
) -> set[str]:
    """The concrete names composed by calls with a literal family prefix."""
    if not families:
        return set()
    found: set[str] = set()
    for py in _walk_files(root, suffix=".py"):
        if _skip_runtime_file(root, py):
            continue
        tree = _parse(py)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                found.update(_family_reads_for_call(node, families))
    return found


def _sdk_root() -> Path:
    return Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def framework_reads() -> frozenset[str]:
    """The literal env reads inside the installed SDK itself."""
    return frozenset(_scan_setting_calls(_sdk_root()))


@lru_cache(maxsize=1)
def framework_dynamic_families() -> dict[str, _DynamicFamily]:
    """Dynamic-family declarations published inside the installed SDK."""
    return _scan_dynamic_families(_sdk_root())


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None


def _compose_files(root: Path) -> list[Path]:
    docker = root / "docker"
    files = sorted(docker.glob("*compose*.y*ml")) if docker.is_dir() else []
    return [f for f in files if f.suffix in {".yml", ".yaml"}]


def _compose_services(document: Any) -> list[dict[str, Any]]:
    services = document.get("services") if isinstance(document, dict) else None
    if not isinstance(services, dict):
        return []
    return [s for s in services.values() if isinstance(s, dict)]


def _compose_env_keys(root: Path) -> dict[str, set[str]]:
    """Per compose file, the keys its ``environment:`` blocks declare."""
    out: dict[str, set[str]] = {}
    for path in _compose_files(root):
        keys: set[str] = set()
        for service in _compose_services(_load_yaml(path)):
            env = service.get("environment")
            if isinstance(env, dict):
                keys.update(str(k) for k in env)
            elif isinstance(env, list):
                keys.update(str(item).split("=", 1)[0].strip() for item in env)
        keys = {k for k in keys if _ENV_NAME.fullmatch(k)}
        if keys:
            out[path.name] = keys
    return out


def _subst_names(value: Any) -> set[str]:
    text = " ".join(map(str, value)) if isinstance(value, list) else str(value)
    names: set[str] = set()
    for inner in _SUBST.findall(text):
        name = re.split(r"[:?\-+]", inner.strip(), maxsplit=1)[0]
        if _ENV_NAME.fullmatch(name):
            names.add(name)
    return names


def _compose_subst_reads(root: Path) -> set[str]:
    """``${VAR}`` substitutions compose itself performs outside ``environment:``."""
    found: set[str] = set()
    for path in _compose_files(root):
        for service in _compose_services(_load_yaml(path)):
            for key in _COMPOSE_SUBST_KEYS & set(service):
                found.update(_subst_names(service[key]))
    return found


def _declared_env_example(root: Path) -> set[str]:
    path = root / ".env.example"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    return {m.group(1) for line in lines if (m := _ENV_DECL.match(line))}


def _mcp_config_env(root: Path) -> list[tuple[str, set[str]]]:
    out: list[tuple[str, set[str]]] = []
    for path in sorted(root.glob("mcp_config*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        servers = document.get("mcpServers") if isinstance(document, dict) else None
        keys: set[str] = set()
        for server in (servers or {}).values() if isinstance(servers, dict) else ():
            env = server.get("env") if isinstance(server, dict) else None
            if isinstance(env, dict):
                keys.update(k for k in env if _ENV_NAME.fullmatch(str(k)))
        if keys:
            out.append((path.name, keys))
    return out


def _framework_known(var: str) -> bool:
    return (
        var in FRAMEWORK_ENV
        or var in RUNTIME_ALLOWLIST
        or var.startswith(_RUNTIME_PREFIXES)
    )


def analyze(root: Path) -> dict[str, Any]:
    """Diff the declared env vars of the connector at ``root`` against its reads."""
    root = Path(root)
    families = dict(framework_dynamic_families())
    families.update(_scan_dynamic_families(root))
    package_reads = (
        _scan_setting_calls(root)
        | _compose_subst_reads(root)
        | _scan_dynamic_family_reads(root, families)
    )
    toggles = _derive_toggle_vars(root)
    code_read = package_reads | toggles | _script_reads(root) | framework_reads()

    declared_env = _declared_env_example(root)
    sources: dict[str, set[str]] = {v: {".env.example"} for v in declared_env}
    for name, keys in _mcp_config_env(root):
        for var in keys:
            sources.setdefault(var, set()).add(name)
    for name, keys in _compose_env_keys(root).items():
        for var in keys:
            sources.setdefault(var, set()).add(f"docker/{name}")

    findings: list[dict[str, Any]] = [
        {"type": "DEAD", "var": var, "sources": sorted(where), "hint": ""}
        for var, where in sorted(sources.items())
        if var not in code_read and not _framework_known(var)
    ]
    findings += [
        {"type": "UNDOCUMENTED", "var": var, "sources": ["(code)"], "hint": ""}
        for var in sorted((package_reads | toggles) - declared_env)
        if not _framework_known(var)
    ]
    return {
        "package": root.resolve().name,
        "code_read_count": len(code_read),
        "findings": findings,
        "drift": len(findings),
    }


def format_report(report: dict[str, Any]) -> str:
    """A human-readable rendering of :func:`analyze`'s report."""
    lines = [f"env-var drift - {report['package']}: {report['drift']} finding(s)"]
    if not report["findings"]:
        lines.append("  clean (declarations match the code-read env surface)")
    for finding in report["findings"]:
        hint = f"  -> {finding['hint']}" if finding.get("hint") else ""
        where = ", ".join(finding.get("sources", []))
        lines.append(f"  [{finding['type']}] {finding['var']}  ({where}){hint}")
    return "\n".join(lines)


_format = format_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect connector env-var drift.")
    parser.add_argument("root", nargs="?", default=".", help="Connector root")
    parser.add_argument("--check", action="store_true", help="Exit 1 on any drift")
    parser.add_argument("--json", action="store_true", help="Emit JSON findings")
    args = parser.parse_args(argv)
    report = analyze(Path(args.root))
    print(json.dumps(report, indent=2) if args.json else format_report(report))
    if args.check and report["drift"]:
        print(
            "\nenv-var drift detected (the code is the source of truth).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
