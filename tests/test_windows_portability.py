"""SCION-CONNECTOR-CONTROL-R034.1: the SDK imports and runs without POSIX-only APIs."""

from __future__ import annotations

import getpass
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from scion_sdk.adapters import bookmark_io, safe_dir
from scion_sdk.adapters.bookmark_models import BookmarkReadError
from scion_sdk.adapters.paper_document_errors import DocumentRefusal
from scion_sdk.adapters.paper_download_files import _verify_existing
from scion_sdk.adapters.paper_download_temp import _open_validation, _temporary
from scion_sdk.adapters.safe_dir import SafeDir
from scion_sdk.auth.browser import FileTokenStore
from scion_sdk.library_state import file_lock
from scion_sdk.tls import material


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hide every POSIX-only name the SDK used to assume."""
    for name in ("fchmod", "getuid", "geteuid"):
        monkeypatch.delattr(os, name, raising=False)
    for name in ("O_NOFOLLOW", "O_NONBLOCK", "O_DIRECTORY"):
        monkeypatch.delattr(os, name, raising=False)
    monkeypatch.setattr(safe_dir, "use_dir_fd", lambda: False)
    monkeypatch.setattr(bookmark_io, "use_dir_fd", lambda: False)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R034.1")
@pytest.mark.parametrize(
    "module",
    ["scion_sdk.library_state", "scion_sdk.auth.browser", "scion_sdk.tls.material"],
)
def test_modules_import_without_fcntl(module: str) -> None:
    code = (
        "import sys, asyncio, ctypes, pathlib, logging, http.server, hashlib\n"
        "import types; stub = types.ModuleType('scion_sdk._file_lock_windows')\n"
        "stub.lock_exclusive = stub.lock_shared = lambda fd, blocking=True: True\n"
        "stub.lock_exclusive_nb = stub.lock_shared_nb = stub.unlock = lambda fd: None\n"
        "sys.modules['scion_sdk._file_lock_windows'] = stub\n"
        "sys.modules['fcntl'] = None; sys.platform = 'win32'\n"
        f"import {module}"
    )
    result = subprocess.run(  # nosec B603 - fixed argv
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R034.1")
def test_token_store_without_fchmod_or_nofollow(tmp_path: Path, windows: None) -> None:
    store = FileTokenStore(tmp_path / "tokens")
    store.set("k", "secret")
    store.set("k", "again")
    assert store.get("k") == "again"


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R034.1")
def test_token_store_refuses_symlink_without_nofollow(
    tmp_path: Path, windows: None
) -> None:
    store = FileTokenStore(tmp_path / "tokens")
    store.root.mkdir()
    victim = tmp_path / "victim"
    victim.write_text("x")
    try:
        store._path("k").symlink_to(victim)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert store.get("k") is None
    with pytest.raises(ValueError):
        store.set("k", "v")
    assert victim.read_text() == "x"


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R034.1")
def test_runtime_root_without_getuid(
    tmp_path: Path, windows: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(getpass, "getuser", lambda: "Dom\\a lice")
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    root = material.default_runtime_root()
    assert root.parent.parent.name == "scion-sdk-Dom_a_lice"


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R034.1")
def test_file_lock_uses_shared_primitive(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    with (
        file_lock(path, timeout=1.0),
        pytest.raises(TimeoutError),
        file_lock(path, timeout=0.1),
    ):
        pass


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R034.1")
def test_safe_dir_fallback_opens_confined_files(tmp_path: Path, windows: None) -> None:
    with _temporary(tmp_path) as (directory, name, fd):
        os.write(fd, b"data")
        assert directory.fd is None
        os.close(_open_validation(directory, name))
        directory.link(name, "final")
    assert (tmp_path / "final").read_bytes() == b"data"
    assert not list(tmp_path.glob(".paper-*"))


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R034.1")
def test_safe_dir_fallback_refuses_symlink_and_traversal(
    tmp_path: Path, windows: None
) -> None:
    (tmp_path / "real").write_text("x")
    try:
        (tmp_path / "link").symlink_to(tmp_path / "real")
    except OSError:
        pytest.skip("symlinks unavailable")
    directory = SafeDir.open(tmp_path)
    with pytest.raises(OSError):
        directory.open_file("link", os.O_RDONLY)
    with pytest.raises(OSError):
        directory.open_file("../real", os.O_RDONLY)
    with pytest.raises(DocumentRefusal):
        _verify_existing(directory, "link", digest="0" * 64, size=1)
    with pytest.raises(OSError):
        SafeDir.open(tmp_path / "link")


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R034.1")
def test_bookmark_fallback_reads_and_refuses_symlink(
    tmp_path: Path, windows: None
) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.html").write_bytes(b"<html>")
    assert bookmark_io._read_file(tmp_path, "sub/b.html", 100) == b"<html>"
    try:
        (tmp_path / "ln").symlink_to(tmp_path / "sub")
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(BookmarkReadError):
        bookmark_io._read_file(tmp_path, "ln/b.html", 100)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R034.1")
def test_safe_dir_helpers_report_platform_capabilities(
    windows: None, tmp_path: Path
) -> None:
    assert safe_dir.no_follow_flags(nonblock=True) in {0, getattr(os, "O_BINARY", 0)}
    assert safe_dir.use_dir_fd() is False or hasattr(os, "O_NOFOLLOW")
    with pytest.raises(safe_dir.SafeDirError):
        SafeDir.open(tmp_path).open_file("a/b", os.O_RDONLY)
