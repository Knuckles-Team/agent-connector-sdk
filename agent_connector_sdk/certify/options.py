"""Validated timeout and OIDC options for connector certification."""

from __future__ import annotations

import argparse
import math

from agent_connector_sdk.auth.client_credentials import ClientCredentialsAuth
from agent_connector_sdk.auth.oidc import (
    ClientCredentialsConfig,
    client_credentials_auth,
)


def _positive_timeout(value: str) -> float:
    """An argparse type accepting only finite positive seconds."""
    try:
        timeout = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be a number") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError("timeout must be finite and positive")
    return timeout


def _oidc_auth(args: argparse.Namespace) -> ClientCredentialsAuth | None:
    """Build SDK client-credentials auth when any OIDC option is present."""
    values = (
        args.oidc_issuer,
        args.oidc_token_url,
        args.oidc_client_id,
        args.oidc_client_secret_ref,
        args.oidc_audience,
        args.oidc_scope,
    )
    if not any(values):
        return None
    config = ClientCredentialsConfig(
        issuer=args.oidc_issuer,
        token_url=args.oidc_token_url,
        client_id=args.oidc_client_id,
        client_secret_ref=args.oidc_client_secret_ref,
        audience=args.oidc_audience,
        scope=args.oidc_scope,
    )
    return client_credentials_auth(config, timeout_seconds=args.timeout)
