"""The ``connector-certify`` console script.

``connector-certify PACKAGE --check -- COMMAND [ARG ...]`` starts the connector's
MCP server over stdio (``--url`` reaches one over streamable HTTP instead), calls
``tools/list`` and compares every preset tool's pins with the live fingerprints.
``--write`` replaces the pins with the live fingerprints. Certification lists
tools only; it never calls one.

The stdio child receives only the MCP client's minimal environment plus
``--placeholder NAME`` (a fixed non-secret value) and ``--env NAME=REFERENCE``
(a resolved ``env://`` or ``openbao://`` reference).

Exit ``0``: every pin matches, or the pins were written. ``1``: a pin is wrong,
missing or empty, or the pins could not be written. ``2``: the checkout is
invalid or the server could not list its tools.
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

from agent_connector_sdk.certify.certification import (
    CertificationReport,
    certify_connector,
)
from agent_connector_sdk.certify.checkout import ConnectorCheckout, load_checkout
from agent_connector_sdk.certify.pins import PinWriteError, write_certified_pins
from agent_connector_sdk.credentials.references import SecretReferenceError
from agent_connector_sdk.credentials.resolution import resolve_secret_reference
from agent_connector_sdk.credentials.resolver import CredentialUnavailableError
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.transports.mcp import McpTransport

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
_STARTUP_ERRORS = (ValueError, CredentialUnavailableError)


def build_parser() -> argparse.ArgumentParser:
    """The command-line parser."""
    parser = argparse.ArgumentParser(
        prog="connector-certify",
        description="Certify a connector's MCP tool-schema pins from tools/list.",
    )
    parser.add_argument("package", type=Path, help="connector checkout root")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="fail on a wrong pin")
    mode.add_argument("--write", action="store_true", help="write the live pins")
    parser.add_argument("--url", default="", help="streamable HTTP endpoint")
    parser.add_argument("--bearer-token", default="", help="reference for --url")
    parser.add_argument("--env", action="append", default=[], metavar="NAME=REFERENCE")
    parser.add_argument("--placeholder", action="append", default=[], metavar="NAME")
    parser.add_argument("--timeout", type=float, default=60.0, help="seconds")
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
        timeout_seconds=args.timeout,
    )


def _configure_logging() -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("connector-certify: %(message)s"))
    logger = logging.getLogger("agent_connector_sdk.certify")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _log_report(report: CertificationReport) -> None:
    if not report.listed:
        _logger.error("connector %s: %s", report.connector, report.reason)
    for verdict in report.verdicts:
        _logger.info(
            "connector %s tool %s: %s (live %s; pins %s) %s",
            report.connector,
            verdict.tool,
            verdict.status.value,
            verdict.live or "-",
            json.dumps(dict(verdict.pins), sort_keys=True),
            verdict.defect,
        )


def _outcome(
    report: CertificationReport, checkout: ConnectorCheckout, *, write: bool
) -> int:
    if not report.listed:
        return 2
    if not write:
        return 0 if report.passed else 1
    try:
        paths = write_certified_pins(checkout, report.verdicts)
    except PinWriteError as exc:
        _logger.error("connector %s: %s", report.connector, exc)
        return 1
    _logger.info("connector %s: wrote %s", report.connector, [p.name for p in paths])
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run ``connector-certify``; returns the process exit code."""
    args = parse_arguments(sys.argv[1:] if argv is None else argv)
    _configure_logging()
    try:
        checkout = load_checkout(args.package)
        endpoint = build_endpoint(args)
    except _STARTUP_ERRORS as exc:
        _logger.error("connector-certify cannot start: %s", exc)
        return 2
    certify = partial(
        certify_connector,
        checkout,
        McpTransport(),
        endpoint,
        timeout_seconds=args.timeout,
    )
    report = anyio.run(certify)
    _log_report(report)
    if args.report is not None:
        document = json.dumps(report.document(), indent=2, sort_keys=True)
        args.report.write_text(document + "\n", encoding="utf-8")
    return _outcome(report, checkout, write=args.write)
