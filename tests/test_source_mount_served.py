"""The workspace mount over a served ``source.*`` backend (SCION-SCM-R002.6)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from source_backend_helpers import SourceBackend

from scion_sdk.source import (
    McpSourceTransport,
    MountRefusedError,
    SourceClient,
    SourceMount,
    SourceRefusedError,
)

FILES = {"src/a.py": b"a = 1\n", "src/b.py": b"b = 2\n", "other/x": b"x\n"}


def _served(backend: SourceBackend) -> FastMCP[Any]:
    server: FastMCP[Any] = FastMCP("source-backend")

    @server.tool()
    async def source_tree(
        repository_id: str,
        ref: str,
        page_size: int,
        path_prefix: str | None = None,
        continuation: str | None = None,
    ) -> dict[str, Any]:
        return await backend.call(
            "tree",
            {
                "repository_id": repository_id,
                "ref": ref,
                "page_size": page_size,
                "path_prefix": path_prefix,
                "continuation": continuation,
            },
        )

    @server.tool()
    async def source_blob(
        repository_id: str, ref: str, path: str, digest: str | None = None
    ) -> dict[str, Any]:
        return await backend.call("blob", {"path": path})

    @server.tool()
    async def source_commit(
        repository_id: str,
        branch: str,
        base_revision: str,
        message: str,
        changes: list[dict[str, Any]],
        operation_id: str,
    ) -> dict[str, Any]:
        return await backend.call(
            "commit",
            {
                "base_revision": base_revision,
                "changes": changes,
                "operation_id": operation_id,
            },
        )

    return server


@pytest.mark.spec("SCION-SCM-R002.6")
async def test_served_mount_read_write_and_conflicting_flush(tmp_path: Path) -> None:
    backend = SourceBackend(FILES)
    async with Client(_served(backend)) as session:
        client = SourceClient(McpSourceTransport(session))
        mount = await SourceMount.start(
            client,
            root=tmp_path / "ws",
            repository_id="repo",
            ref="main",
            branch="work",
            prefixes=("src",),
        )
        assert await mount.read("src/a.py") == FILES["src/a.py"]
        with pytest.raises(MountRefusedError) as denied:
            await mount.read("other/x")
        assert denied.value.reason == "path_denied"

        mount.write("src/a.py", b"a = 2\n")
        mount.write("src/c.py", b"c = 3\n")
        await mount.flush()
        assert len(backend.commits) == 1
        assert backend.files["src/a.py"] == b"a = 2\n"
        assert backend.files["src/c.py"] == b"c = 3\n"

        mount.write("src/b.py", b"b = 9\n")
        backend.revision = "r77"
        with pytest.raises(SourceRefusedError) as conflict:
            await mount.flush()
        assert conflict.value.reason == "conflict"
        assert [p.path for p in mount.pending] == ["src/b.py"]
        assert len(backend.commits) == 1
        assert backend.files["src/b.py"] == FILES["src/b.py"]
