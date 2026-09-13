"""The ``connector-sync`` console script.

``connector-sync --config runner.yml`` serves every configured connector until
stopped; ``--once`` runs one full cycle per connector and exits ``0`` only when
every connector succeeded. Exit ``2`` means the runner could not start.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

import anyio

from agent_connector_sdk.config import setting
from agent_connector_sdk.credentials.references import SecretReferenceError
from agent_connector_sdk.discovery import (
    ExtensionActivationError,
    ExtensionDiscoveryError,
)
from agent_connector_sdk.runner.composition import default_services
from agent_connector_sdk.runner.errors import RunnerConfigurationError
from agent_connector_sdk.runner.logs import configure_logging
from agent_connector_sdk.runner.static_registry import (
    StaticConfigRegistry,
    load_runner_config,
)
from agent_connector_sdk.runner.supervisor import ConnectorSyncRunner

__all__ = ["build_parser", "default_state_dir", "main"]

_logger = logging.getLogger(__name__)

_STARTUP_ERRORS = (
    RunnerConfigurationError,
    ExtensionActivationError,
    ExtensionDiscoveryError,
    SecretReferenceError,
    LookupError,
)


def default_state_dir() -> Path:
    """``$XDG_STATE_HOME/connector-sync``, else ``~/.local/state/connector-sync``."""
    base = setting("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "connector-sync"


def build_parser() -> argparse.ArgumentParser:
    """The command-line parser."""
    parser = argparse.ArgumentParser(
        prog="connector-sync",
        description="Provision connector content and sync connector presets.",
    )
    parser.add_argument("--config", type=Path, required=True, help="runner YAML")
    parser.add_argument(
        "--state-dir", type=Path, default=None, help="checkpoint directory"
    )
    parser.add_argument("--sink", default="epistemic_graph", help="sink extension")
    parser.add_argument("--once", action="store_true", help="one cycle, then exit")
    parser.add_argument("--log-format", choices=("json", "text"), default="json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the connector-sync runner; returns the process exit code."""
    args = build_parser().parse_args(argv)
    configure_logging(args.log_format)
    try:
        config = load_runner_config(args.config)
        services = default_services(
            config.settings,
            state_dir=args.state_dir or default_state_dir(),
            sink_name=args.sink,
        )
    except _STARTUP_ERRORS as exc:
        _logger.error("connector-sync cannot start: %s", exc)
        return 2
    runner = ConnectorSyncRunner(StaticConfigRegistry(args.config), services)
    if args.once:
        results = anyio.run(runner.run_once)
        return 0 if all(results.values()) else 1
    anyio.run(runner.run_forever)
    return 0
