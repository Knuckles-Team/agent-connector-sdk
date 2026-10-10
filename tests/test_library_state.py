"""SDK-CONNECTOR-CONTROL-R034: library file path resolution and file locking."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from agent_connector_sdk.library_state import file_lock, get_library_file_path


def test_get_library_file_path_resolves_from_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AGENT_STATE_DIR", str(tmp_path))
    first = get_library_file_path("demo-connector", "library.json")
    second = get_library_file_path("demo-connector", "library.json")
    assert first == second == tmp_path / "demo-connector" / "library.json"


def test_file_lock_serializes_two_writers(tmp_path: Path) -> None:
    target = tmp_path / "library.json"
    order: list[str] = []

    def writer(name: str, hold_seconds: float) -> None:
        with file_lock(target, timeout=5.0):
            order.append(f"{name}-start")
            time.sleep(hold_seconds)
            order.append(f"{name}-end")

    first = threading.Thread(target=writer, args=("first", 0.1))
    second = threading.Thread(target=writer, args=("second", 0.0))
    first.start()
    time.sleep(0.02)
    second.start()
    first.join(timeout=5)
    second.join(timeout=5)

    # The second writer's start never appears between the first's start and end.
    first_start = order.index("first-start")
    first_end = order.index("first-end")
    assert "second-start" not in order[first_start + 1 : first_end]


def test_file_lock_times_out_when_held(tmp_path: Path) -> None:
    target = tmp_path / "library.json"
    ready = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with file_lock(target, timeout=5.0):
            ready.set()
            release.wait(timeout=5)

    thread = threading.Thread(target=holder)
    thread.start()
    assert ready.wait(timeout=5)
    try:
        with pytest.raises(TimeoutError), file_lock(target, timeout=0.1):
            pass
    finally:
        release.set()
        thread.join(timeout=5)
