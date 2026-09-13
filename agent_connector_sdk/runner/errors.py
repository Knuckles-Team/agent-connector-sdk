"""Errors the connector-sync runner raises."""

from __future__ import annotations

__all__ = [
    "CheckpointStoreError",
    "CredentialResolutionError",
    "RunnerConfigurationError",
    "SinkReceiptError",
]


class RunnerConfigurationError(ValueError):
    """The runner configuration or a connector package is unusable.

    Messages name fields, never their values.
    """


class CredentialResolutionError(PermissionError):
    """A connector's credential reference could not be resolved; no session opens."""


class SinkReceiptError(RuntimeError):
    """A sink receipt does not acknowledge exactly what was submitted."""


class CheckpointStoreError(RuntimeError):
    """Checkpoint state is unreadable, corrupt or addressed by an unsafe name."""
