"""The ``connector-certify`` console script.

``connector-certify -- COMMAND [ARG ...]`` starts the connector's MCP server over
stdio (``--url`` reaches one over streamable HTTP instead), calls ``tools/list``,
reads ``connector://resources`` and checks every declared preset tool against its
live definition. Certification lists tools only; it never calls one.

The stdio child receives only the MCP client's minimal environment plus
``--placeholder NAME`` (a fixed non-secret value) and ``--env NAME=REFERENCE``
(a resolved ``env://`` or ``openbao://`` reference).

``--predecessor-url`` adds the successor tool parity check
(SCION-CONNECTOR-CONTROL-R020.4) against a separately supplied live endpoint:
every predecessor tool must be kept or split into ``<tool>_<action>`` tools, and
no action-dispatch tool may remain; a lost tool fails certification. The
operator must authenticate that endpoint as the actual predecessor.
Per-operation coverage of a renamed tool is not checked.

Exit ``0``: every declared preset tool is valid. ``1``: a tool is missing or
invalid. ``2``: the server could not list its tools or declaration.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from functools import partial
from pathlib import Path

import anyio

from scion_sdk.certify.certification import (
    CertificationReport,
    certify_connector,
)
from scion_sdk.certify.options import _oidc_auth, _positive_timeout
from scion_sdk.credentials.references import SecretReferenceError
from scion_sdk.credentials.resolution import resolve_secret_reference
from scion_sdk.ports.session import TransportEndpoint

__all__ = [
    "PLACEHOLDER_VALUE",
    "build_endpoint",
    "build_parser",
    "main",
    "parse_arguments",
]

#: The value ``--placeholder NAME`` gives ``NAME``: recognisably not a credential.
PLACEHOLDER_VALUE = "connector-certify-placeholder"

_logger = logging.getLogger(__name__)


def _add_oidc_arguments(parser: argparse.ArgumentParser) -> None:
    oidc = parser.add_argument_group("OIDC client credentials for --url")
    source = oidc.add_mutually_exclusive_group()
    source.add_argument("--oidc-issuer", default="", help="OIDC issuer URL")
    source.add_argument("--oidc-token-url", default="", help="OAuth token URL")
    oidc.add_argument("--oidc-client-id", default="", help="OAuth client ID")
    oidc.add_argument(
        "--oidc-client-secret-ref",
        default="",
        help="secret reference, normally openbao://mount/path#field",
    )
    oidc.add_argument("--oidc-audience", default="", help="token audience")
    oidc.add_argument("--oidc-scope", default="", help="space-separated scopes")


def build_parser() -> argparse.ArgumentParser:
    """The command-line parser."""
    parser = argparse.ArgumentParser(
        prog="connector-certify",
        description="Certify a connector's declared sync tools from tools/list.",
    )
    parser.add_argument("--url", default="", help="streamable HTTP endpoint")
    parser.add_argument(
        "--predecessor-url",
        default="",
        help="predecessor endpoint for the successor tool parity check",
    )
    parser.add_argument(
        "--predecessor-bearer-token", default="", help="predecessor token reference"
    )
    parser.add_argument("--bearer-token", default="", help="reference for --url")
    _add_oidc_arguments(parser)
    parser.add_argument("--env", action="append", default=[], metavar="NAME=REFERENCE")
    parser.add_argument("--placeholder", action="append", default=[], metavar="NAME")
    parser.add_argument(
        "--timeout", type=_positive_timeout, default=60.0, help="seconds"
    )
    parser.add_argument("--report", type=Path, help="write the JSON report here")
    parser.epilog = "Everything after -- is the stdio server command and its arguments."
    return parser


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    """Parse the options before ``--``; ``command`` holds everything after it."""
    items = list(argv)
    split = items.index("--") if "--" in items else len(items)
    args = build_parser().parse_args(items[:split])
    args.command = items[split + 1 :]
    return args


def build_endpoint(args: argparse.Namespace) -> TransportEndpoint:
    """The endpoint the arguments describe, with references resolved.

    Raises:
        ValueError: the endpoint or an ``--env`` item is malformed.
        CredentialUnavailableError: a reference does not resolve.
    """
    if args.predecessor_bearer_token and not args.predecessor_url:
        raise ValueError("predecessor token requires a predecessor URL")
    command = list(args.command)
    env = dict.fromkeys(args.placeholder, PLACEHOLDER_VALUE)
    for item in args.env:
        name, separator, reference = item.partition("=")
        if not (name and separator):
            raise SecretReferenceError("--env takes NAME=REFERENCE")
        env[name] = resolve_secret_reference(reference)
    token = resolve_secret_reference(args.bearer_token) if args.bearer_token else ""
    return TransportEndpoint(
        url=args.url,
        command=command[0] if command else "",
        args=tuple(command[1:]),
        env=env,
        bearer_token=token,
        auth=_oidc_auth(args),
        timeout_seconds=args.timeout,
    )


def _configure_logging() -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("connector-certify: %(message)s"))
    logger = logging.getLogger("scion_sdk.certify")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _log_report(report: CertificationReport) -> None:
    if not report.listed:
        _logger.error("connector %s: %s", report.connector, report.reason)
    if report.exact_name_check is not None:
        _logger.info("predecessor exact-name check: %s", report.exact_name_reason)
    for verdict in report.verdicts:
        _logger.info(
            "connector %s tool %s: %s (live %s) %s",
            report.connector,
            verdict.tool,
            verdict.status.value,
            verdict.live or "-",
            verdict.defect,
        )


def _predecessor_endpoint(args: argparse.Namespace) -> TransportEndpoint | None:
    if not args.predecessor_url:
        return None
    token = (
        resolve_secret_reference(args.predecessor_bearer_token)
        if args.predecessor_bearer_token
        else ""
    )
    return TransportEndpoint(
        url=args.predecessor_url,
        bearer_token=token,
        timeout_seconds=args.timeout,
    )


async def _certify_endpoint(args: argparse.Namespace) -> CertificationReport:
    from scion_sdk.transports.mcp import McpTransport

    endpoint = await anyio.to_thread.run_sync(
        partial(build_endpoint, args), abandon_on_cancel=True
    )
    return await certify_connector(
        McpTransport(),
        endpoint,
        timeout_seconds=args.timeout,
        predecessor=_predecessor_endpoint(args),
    )


async def _run_certification(args: argparse.Namespace) -> CertificationReport:
    try:
        with anyio.fail_after(args.timeout):
            return await _certify_endpoint(args)
    except TimeoutError:
        return CertificationReport(
            connector="",
            server="",
            listed=False,
            reason="connector certification timed out before tools/list completed",
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Run ``connector-certify``; returns the process exit code."""
    args = parse_arguments(sys.argv[1:] if argv is None else argv)
    _configure_logging()
    try:
        report = anyio.run(partial(_run_certification, args))
    except Exception:
        _logger.error("connector-certify cannot start: invalid endpoint or credentials")
        return 2
    _log_report(report)
    if args.report is not None:
        document = json.dumps(report.document(), indent=2, sort_keys=True)
        args.report.write_text(document + "\n", encoding="utf-8")
    if not report.listed:
        return 2
    return 0 if report.passed else 1
