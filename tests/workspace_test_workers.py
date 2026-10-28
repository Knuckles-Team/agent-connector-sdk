"""Worker functions for end-to-end workspace process tests."""

from __future__ import annotations

import os
import socket
import time
from pathlib import Path

from agent_connector_sdk.adapters.workspace_models import (
    WorkspaceFile,
    WorkspaceOutcome,
    WorkspaceRequest,
)
from agent_connector_sdk.adapters.workspace_reader import WorkspaceReader


def offline_read(file: WorkspaceFile, request: WorkspaceRequest) -> WorkspaceOutcome:
    """Run the real reader while refusing child-process network access."""
    original_connect = socket.socket.connect
    original_create = socket.create_connection

    def deny(*args, **kwargs):
        raise AssertionError("workspace parser attempted network access")

    socket.socket.connect = deny
    socket.create_connection = deny
    try:
        return WorkspaceReader(
            Path(request.root_authority), authority=request.root_authority
        )._read_one(file, request)
    finally:
        socket.socket.connect = original_connect
        socket.create_connection = original_create


def coordinated_read(
    file: WorkspaceFile, request: WorkspaceRequest
) -> WorkspaceOutcome:
    """Record actual worker intervals after two independent workers start."""
    root = Path(request.root_authority)
    marker = root / f"{file.relative_path}.started"
    marker.write_text(str(time.monotonic()))
    until = time.monotonic() + 10
    while len(list(root.glob("*.started"))) < 2 and time.monotonic() < until:
        time.sleep(0.01)
    time.sleep(0.1)
    (root / f"{file.relative_path}.finished").write_text(str(time.monotonic()))
    return WorkspaceOutcome(file=file, outcome="ok", elapsed_seconds=0.1)


def blocking_read(file: WorkspaceFile, request: WorkspaceRequest) -> WorkspaceOutcome:
    """Announce the worker PID and block until the parent cancels it."""
    marker = Path(request.root_authority) / "worker.pid"
    pending = marker.with_suffix(".pending")
    pending.write_text(str(os.getpid()))
    pending.replace(marker)
    time.sleep(60)
    return WorkspaceOutcome(file=file, outcome="ok", elapsed_seconds=60.0)


def maximum_parallelism(root: Path, files: tuple[WorkspaceFile, ...]) -> int:
    """Measure worker overlap from their monotonic start and finish times."""
    events = []
    for file in files:
        start = float((root / f"{file.relative_path}.started").read_text())
        end = float((root / f"{file.relative_path}.finished").read_text())
        events.extend(((start, 1), (end, -1)))
    active = 0
    maximum = 0
    for _, change in sorted(events):
        active += change
        maximum = max(maximum, active)
    return maximum
