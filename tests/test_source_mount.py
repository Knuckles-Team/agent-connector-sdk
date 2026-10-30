"""Sparse virtual workspace over the source client (SCION-SCM-R002)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError
from source_backend_helpers import SourceBackend

from agent_connector_sdk.source import (
    MountRefusedError,
    MountState,
    PendingEntry,
    SourceClient,
    SourceMount,
    SourceRefusedError,
)

FILES = {
    "src/a.py": b"a = 1\n",
    "src/b.py": b"b = 2\n",
    "docs/readme.md": b"docs\n",
    "secret/key": b"private\n",
}


async def _mount(
    tmp_path: Path, backend: SourceBackend | None = None, prefixes=("src",)
):
    backend = backend or SourceBackend(FILES)
    client = SourceClient(backend)
    mount = await SourceMount.start(
        client,
        root=tmp_path / "ws",
        repository_id="repo",
        ref="main",
        branch="work",
        prefixes=prefixes,
    )
    return mount, backend


@pytest.mark.spec("SCION-SCM-R002.1")
async def test_mount_state_and_entry_models_are_typed(tmp_path: Path) -> None:
    mount, _ = await _mount(tmp_path)
    state = mount.state
    assert isinstance(state, MountState)
    assert (state.repository_id, state.base_revision, state.prefixes) == (
        "repo",
        "r1",
        ("src",),
    )
    assert state.pending_changeset_id is None
    entries = await mount.listdir("src")
    assert (entries[0].path, entries[0].mode, entries[0].digest) == (
        "src/a.py",
        "100644",
        hashlib.sha256(FILES["src/a.py"]).hexdigest(),
    )
    mount.write("src/new.py", b"x")
    pending = mount.pending
    assert pending == (
        PendingEntry(
            path="src/new.py",
            operation="put",
            blob_ref=hashlib.sha256(b"x").hexdigest(),
        ),
    )
    assert mount.state.pending_changeset_id
    with pytest.raises(ValidationError):
        state.base_revision = "r9"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        MountState(repository_id="r", base_revision="1", prefixes=())


@pytest.mark.spec("SCION-SCM-R002.2")
async def test_reads_materialize_and_writes_accumulate(tmp_path: Path) -> None:
    mount, backend = await _mount(tmp_path)
    assert await mount.read("src/a.py") == FILES["src/a.py"]
    assert (tmp_path / "ws" / "src" / "a.py").read_bytes() == FILES["src/a.py"]
    assert await mount.read("src/a.py") == FILES["src/a.py"]
    assert backend.blob_reads == 1 and mount.cache_hits == 1
    mount.write("src/a.py", b"first")
    mount.write("src/a.py", b"second")
    mount.delete("src/b.py")
    assert [p.operation for p in mount.pending] == ["put", "delete"]
    assert await mount.read("src/a.py") == b"second"
    assert backend.files["src/a.py"] == FILES["src/a.py"] and backend.revision == "r1"
    listed = {e.path for e in await mount.listdir("src")}
    assert "src/b.py" not in listed
    receipt = await mount.flush()
    assert len(backend.commits) == 1 and receipt.revision == "r2"
    assert backend.files["src/a.py"] == b"second" and "src/b.py" not in backend.files
    assert mount.pending == () and mount.state.base_revision == "r2"


async def test_mount_composes_the_source_client(tmp_path: Path) -> None:
    mount, backend = await _mount(tmp_path)
    await mount.read("src/a.py")
    assert not (tmp_path / "ws" / ".git").exists()
    assert {p.name for p in (tmp_path / "ws").iterdir()} == {"src"}
    assert not (tmp_path / "ws" / "docs").exists()
    assert backend.blob_reads == 1


@pytest.mark.spec("SCION-SCM-R002.4")
async def test_refusals_preserve_pending_changeset(tmp_path: Path) -> None:
    with pytest.raises(MountRefusedError) as error:
        await SourceMount.start(
            object(),
            root=tmp_path / "x",
            repository_id="repo",
            ref="main",
            branch="work",
            prefixes=("src",),
        )
    assert error.value.reason == "client_not_admitted"
    client = SourceClient(SourceBackend(FILES))
    for prefixes, reason in (((), "unknown_prefix"), (("nope",), "unknown_prefix")):
        with pytest.raises(MountRefusedError) as error:
            await SourceMount.start(
                client,
                root=tmp_path / "y",
                repository_id="repo",
                ref="main",
                branch="work",
                prefixes=prefixes,
            )
        assert error.value.reason == reason

    mount, backend = await _mount(tmp_path)
    for bad in (
        "../x",
        "src/../secret/key",
        "/etc/passwd",
        "src//a.py",
        "docs/readme.md",
    ):
        with pytest.raises(MountRefusedError) as error:
            await mount.read(bad)
        assert error.value.reason == "path_denied", bad
        with pytest.raises(MountRefusedError):
            mount.write(bad, b"x")
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "ws" / "src").symlink_to(outside)
    with pytest.raises(MountRefusedError) as error:
        mount.write("src/escape.py", b"x")
    assert error.value.reason == "path_denied" and not list(outside.iterdir())
    (tmp_path / "ws" / "src").unlink()

    mount.write("src/a.py", b"mine")
    backend.revision = "r9"
    with pytest.raises(SourceRefusedError) as conflict:
        await mount.flush()
    assert conflict.value.reason == "conflict"
    assert [p.path for p in mount.pending] == ["src/a.py"]
    assert await mount.read("src/a.py") == b"mine"
    assert backend.commits == []


@pytest.mark.spec("SCION-SCM-R002.5")
async def test_mount_events_bind_receipts_without_secrets(tmp_path: Path) -> None:
    mount, _ = await _mount(tmp_path)
    await mount.read("src/a.py")
    await mount.read("src/a.py")
    mount.write("src/a.py", b"changed")
    receipt = await mount.flush()
    flush = mount.events[-1]
    assert flush["event"] == "flush"
    assert flush["repository_id"] == "repo" and flush["prefixes"] == ["src"]
    assert flush["reads"] == 2 and flush["cache_hits"] == 1
    assert flush["receipt"] == receipt.provenance.receipt_ref
    assert flush["outcomes"] == [{"path": "src/a.py", "outcome": "applied"}]
    assert len(flush["changeset"]) == 64
    dumped = str(mount.events)
    assert str(tmp_path) not in dumped and "changed" not in dumped
