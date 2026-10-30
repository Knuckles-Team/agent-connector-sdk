"""Check a connector's declared env vars against the vars its code reads (SCION-CONNECTOR-CONTROL-R014.14).

Replaces ``agent_utilities.mcp.check_env_var_drift`` for connectors. The code
is the authority on which variables exist. A connector declares them in
``.env.example``, in every ``mcp_config*.json`` ``env`` block, and in
``docker/*compose*.yml`` ``environment:`` blocks. This module diffs those
declarations against the code-read set:

- ``DEAD``: declared, but no code reads it. Remove it.
Variables the SDK reads on the connector's behalf (``SDK_CONSUMED_ENV`` and
``SDK_CONSUMED_ENV_PATTERNS``: the TLS profile settings and the settings behind the
server parser's flag defaults) are never ``DEAD``.

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

    python -m scion_sdk.mcp.env_drift            # report
    python -m scion_sdk.mcp.env_drift --check    # exit 1 on drift
    python -m scion_sdk.mcp.env_drift --json     # machine-readable
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, TextIO

from scion_sdk.mcp._env_drift_declared import (
    _compose_env_keys,
    _compose_subst_reads,
    _declared_env_example,
    _mcp_config_env,
)
from scion_sdk.mcp._env_drift_families import (
    DynamicFamily,
    _scan_dynamic_families,
    _scan_dynamic_family_reads,
)
from scion_sdk.mcp._env_drift_reads import _scan_setting_calls, _script_reads
from scion_sdk.mcp._env_drift_toggles import _derive_toggle_vars
from scion_sdk.mcp.parser import PARSER_ENV
from scion_sdk.tls.selection import (
    SDK_CONSUMED_ENV as _TLS_CONSUMED_ENV,
)
from scion_sdk.tls.selection import (
    SDK_CONSUMED_ENV_PATTERNS,
)

#: Settings the SDK reads for a connector: the TLS selection and the server parser.
SDK_CONSUMED_ENV: frozenset[str] = _TLS_CONSUMED_ENV | PARSER_ENV

__all__ = [
    "FRAMEWORK_ENV",
    "RUNTIME_ALLOWLIST",
    "SDK_CONSUMED_ENV",
    "SDK_CONSUMED_ENV_PATTERNS",
    "analyze",
    "format_report",
    "framework_dynamic_families",
    "framework_reads",
    "main",
]

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


_SDK_ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def framework_reads() -> frozenset[str]:
    """The literal env reads inside the installed SDK itself."""
    return frozenset(_scan_setting_calls(_SDK_ROOT))


@lru_cache(maxsize=1)
def framework_dynamic_families() -> dict[str, DynamicFamily]:
    """Dynamic-family declarations published inside the installed SDK."""
    return _scan_dynamic_families(_SDK_ROOT)


def _framework_known(var: str) -> bool:
    return (
        var in FRAMEWORK_ENV
        or var in RUNTIME_ALLOWLIST
        or var.startswith(_RUNTIME_PREFIXES)
    )


_SDK_CONSUMED = [re.compile(p) for p in SDK_CONSUMED_ENV_PATTERNS]


def _sdk_consumed(var: str) -> bool:
    """True when the SDK reads ``var`` for the connector (TLS profile settings)."""
    return var in SDK_CONSUMED_ENV or any(p.match(var) for p in _SDK_CONSUMED)


def _code_reads(root: Path) -> tuple[set[str], set[str]]:
    """``(package reads incl. toggles, every read incl. scripts and the SDK)``."""
    families = {**framework_dynamic_families(), **_scan_dynamic_families(root)}
    documentable = (
        _scan_setting_calls(root)
        | _compose_subst_reads(root)
        | _scan_dynamic_family_reads(root, families)
        | _derive_toggle_vars(root)
    )
    return documentable, documentable | _script_reads(root) | framework_reads()


def _declared_sources(root: Path) -> tuple[set[str], dict[str, set[str]]]:
    """``(.env.example vars, var -> files that declare it)``."""
    declared_env = _declared_env_example(root)
    sources: dict[str, set[str]] = {v: {".env.example"} for v in declared_env}
    for name, keys in _mcp_config_env(root):
        for var in keys:
            sources.setdefault(var, set()).add(name)
    for name, keys in _compose_env_keys(root).items():
        for var in keys:
            sources.setdefault(var, set()).add(f"docker/{name}")
    return declared_env, sources


def _findings(
    *,
    documentable: set[str],
    code_read: set[str],
    declared_env: set[str],
    sources: dict[str, set[str]],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = [
        {"type": "DEAD", "var": var, "sources": sorted(where), "hint": ""}
        for var, where in sorted(sources.items())
        if var not in code_read and not _framework_known(var) and not _sdk_consumed(var)
    ]
    findings += [
        {"type": "UNDOCUMENTED", "var": var, "sources": ["(code)"], "hint": ""}
        for var in sorted(documentable - declared_env)
        if not _framework_known(var)
    ]
    return findings


def analyze(root: Path) -> dict[str, Any]:
    """Diff the declared env vars of the connector at ``root`` against its reads."""
    root = Path(root)
    documentable, code_read = _code_reads(root)
    declared_env, sources = _declared_sources(root)
    findings = _findings(
        documentable=documentable,
        code_read=code_read,
        declared_env=declared_env,
        sources=sources,
    )
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


def main(argv: list[str] | None = None, out: TextIO | None = None) -> int:
    """Run the drift check; the report goes to ``out`` (stdout by default), notices to stderr."""
    stream = out if out is not None else sys.stdout
    parser = argparse.ArgumentParser(description="Detect connector env-var drift.")
    parser.add_argument("root", nargs="?", default=".", help="Connector root")
    parser.add_argument("--check", action="store_true", help="Exit 1 on any drift")
    parser.add_argument("--json", action="store_true", help="Emit JSON findings")
    args = parser.parse_args(argv)
    report = analyze(Path(args.root))
    print(
        json.dumps(report, indent=2) if args.json else format_report(report),
        file=stream,
    )
    if args.check and report["drift"]:
        print(
            "\nenv-var drift detected (the code is the source of truth).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
