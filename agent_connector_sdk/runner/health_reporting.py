"""Optional-health call sites: one statement, no branch, at every caller.

The scheduler loop and the workers hold ``RunnerHealth | None`` --
``None`` in the handful of tests that build ``RunnerServices`` directly
without exercising the health surface. An inline ``if health is not None:``
at each of those call sites would add a branch to an existing function on
every call, which the complexity gate (cyclomatic/cognitive, diff-scoped)
treats as a regression; these free functions carry that branch once instead,
so a caller's own control flow never changes shape.
"""

from __future__ import annotations

from agent_connector_sdk.runner.health_state import RunnerHealth

__all__ = [
    "note_credentials",
    "note_cycle_failure",
    "note_cycle_success",
    "note_heartbeat",
    "note_registry_loaded",
]


def note_heartbeat(health: RunnerHealth | None) -> None:
    """Beat ``health`` when tracking is enabled; a no-op otherwise."""
    if health is not None:
        health.heartbeat()


def note_registry_loaded(
    health: RunnerHealth | None, connectors: tuple[str, ...]
) -> None:
    """Sync ``health``'s registry state when tracking is enabled."""
    if health is not None:
        health.sync_registry(connectors)


def note_credentials(
    health: RunnerHealth | None, connector: str, *, ok: bool, error: str = ""
) -> None:
    """Record a credential-resolution outcome when tracking is enabled."""
    if health is not None:
        health.record_credentials(connector, ok=ok, error=error)


def note_cycle_success(health: RunnerHealth | None, connector: str) -> None:
    """Record a successful cycle when tracking is enabled."""
    if health is not None:
        health.record_cycle_success(connector)


def note_cycle_failure(
    health: RunnerHealth | None, connector: str, *, next_retry_seconds: float | None
) -> None:
    """Record a failed cycle when tracking is enabled."""
    if health is not None:
        health.record_cycle_failure(connector, next_retry_seconds=next_retry_seconds)
