"""SCION-SOURCE-INGEST-R011: the ingest-worker command."""

from __future__ import annotations

import os
import signal
import threading
from typing import Any

import pytest

from scion_sdk.runner import ingest_worker_cli as cli

pytestmark = pytest.mark.spec("SCION-SOURCE-INGEST-R011")
ARGS = ["--engine-endpoint", "tls://engine:1"]


def _unreachable(endpoint: str) -> Any:
    raise OSError("down")


def test_unreachable_engine_exits_2() -> None:
    assert cli.main(ARGS, connect=_unreachable) == 2


def test_missing_task_queue_method_exits_2() -> None:
    class NoQueue:
        def worker_admit(self, *a: Any) -> dict[str, Any]:
            return {}

    assert cli.main(ARGS, connect=lambda e: NoQueue()) == 2


def test_sigterm_drains_cleanly() -> None:
    class Engine:
        def worker_admit(self, *a: Any) -> dict[str, Any]:
            threading.Timer(0.05, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
            return {
                "slots": 1,
                "reserved_lane": "g",
                "lease_seconds": 1,
                "retry_after_seconds": 0.01,
            }

        def task_queue_claim(self, *a: Any) -> None:
            return None

        def task_queue_ack(self, *a: Any) -> None: ...

    old = signal.getsignal(signal.SIGTERM)
    try:
        assert cli.main(ARGS, connect=lambda e: Engine()) == 0
    finally:
        signal.signal(signal.SIGTERM, old)
