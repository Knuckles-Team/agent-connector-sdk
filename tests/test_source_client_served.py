"""The source client composed behind a registered connector tool (SCION-SCM-R001.3/.6)."""

from __future__ import annotations

import base64
import hashlib
from typing import Any

import pytest
from fastmcp import Client, FastMCP

from agent_connector_sdk.mcp.tool_surface import register_tool_surface
from agent_connector_sdk.source import (
    BlobRequest,
    ChangeEntry,
    CommitRequest,
    McpSourceTransport,
    SourceClient,
    SourceRefusedError,
    TreeRequest,
)

CONTENT = b"served bytes\n"
DIGEST = hashlib.sha256(CONTENT).hexdigest()


def _backend() -> tuple[FastMCP[Any], dict[str, Any]]:
    """A controlled served backend exposing source.* as MCP tools."""
    state: dict[str, Any] = {"revision": "r1", "commits": 0, "blob_reads": 0}
    server: FastMCP[Any] = FastMCP("source-backend")

    @server.tool()
    def source_tree(
        repository_id: str,
        ref: str,
        page_size: int,
        path_prefix: str | None = None,
        continuation: str | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "ok",
            "result": {
                "revision": state["revision"],
                "entries": [
                    {"path": "src/a.py", "mode": "100644", "digest": DIGEST, "size": 13}
                ],
                "continuation": None,
            },
        }

    @server.tool()
    def source_blob(
        repository_id: str, ref: str, path: str, digest: str | None = None
    ) -> dict[str, Any]:
        state["blob_reads"] += 1
        return {
            "status": "ok",
            "result": {
                "revision": state["revision"],
                "content_base64": base64.b64encode(CONTENT).decode(),
            },
        }

    @server.tool()
    def source_commit(
        repository_id: str,
        branch: str,
        base_revision: str,
        message: str,
        changes: list[dict[str, Any]],
        operation_id: str,
    ) -> dict[str, Any]:
        if base_revision != state["revision"]:
            return {"status": "refused", "reason": "conflict"}
        state["commits"] += 1
        state["revision"] = "r2"
        return {
            "status": "ok",
            "result": {
                "revision": "r2",
                "receipt_ref": f"receipt:{operation_id}",
                "outcomes": [{"path": "src/a.py", "outcome": "applied"}],
            },
        }

    return server, state


class DevTools:
    """Development tools the connector registers; built per call with the session."""

    def __init__(self, session: Any) -> None:
        self._client = SourceClient(McpSourceTransport(session))

    async def read_source_page(self, repository_id: str, ref: str) -> dict[str, Any]:
        """List the tree of a repository ref.

        GET /source/tree
        """
        page = await self._client.tree(
            TreeRequest(repository_id=repository_id, ref=ref)
        )
        blob = await self._client.blob(
            BlobRequest(
                repository_id=repository_id,
                ref=ref,
                path=page.entries[0].path,
                digest=page.entries[0].digest,
            )
        )
        warm = await self._client.blob(
            BlobRequest(
                repository_id=repository_id,
                ref=ref,
                path=page.entries[0].path,
                digest=page.entries[0].digest,
            )
        )
        return {
            "paths": [e.path for e in page.entries],
            "cold": [blob.cache, blob.digest, blob.content.decode()],
            "warm": [warm.cache, warm.digest, warm.content.decode()],
        }

    async def commit_source_change(self, base_revision: str) -> dict[str, Any]:
        """Commit one change to a repository branch.

        POST /source/commit
        """
        try:
            receipt = await self._client.commit(
                CommitRequest(
                    repository_id="repo",
                    branch="work",
                    base_revision=base_revision,
                    message="change",
                    changes=(
                        ChangeEntry(
                            path="src/a.py", operation="put", content_base64="aGk="
                        ),
                    ),
                )
            )
        except SourceRefusedError as error:
            return {"refused": error.reason}
        return {"revision": receipt.revision, "receipt": receipt.provenance.receipt_ref}


@pytest.mark.spec("SCION-SCM-R001.3")
@pytest.mark.spec("SCION-SCM-R001.6")
async def test_served_client_pages_and_conflict_refusal() -> None:
    backend, state = _backend()
    async with Client(backend) as session:
        connector: FastMCP[Any] = FastMCP("repository-manager")
        register_tool_surface(
            connector,
            service="repository-manager",
            client_cls=DevTools,
            get_client=lambda: DevTools(session),
        )
        async with Client(connector) as caller:
            tools = {t.name for t in await caller.list_tools()}
            read = next(n for n in tools if n.endswith("read_source_page"))
            commit = next(n for n in tools if n.endswith("commit_source_change"))
            page = (
                await caller.call_tool(read, {"repository_id": "repo", "ref": "main"})
            ).structured_content
            assert page["paths"] == ["src/a.py"]
            assert page["cold"] == ["miss", DIGEST, CONTENT.decode()]
            assert page["warm"] == ["hit", DIGEST, CONTENT.decode()]
            assert state["blob_reads"] == 1
            good = (
                await caller.call_tool(commit, {"base_revision": "r1"})
            ).structured_content
            assert good["revision"] == "r2" and good["receipt"].startswith(
                "receipt:commit-"
            )
            assert state["commits"] == 1
            stale = (
                await caller.call_tool(commit, {"base_revision": "r1"})
            ).structured_content
            assert stale["refused"] == "conflict"
            assert state["commits"] == 1 and state["revision"] == "r2"
