"""A controlled served ``source.*`` backend shared by the SCM tests."""

from __future__ import annotations

import base64
import hashlib
from typing import Any


class SourceBackend:
    """In-memory repository: path -> bytes at one revision, optimistic commits."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = dict(files)
        self.revision = "r1"
        self.commits: list[dict[str, Any]] = []
        self.blob_reads = 0

    def tree(self, payload: dict[str, Any]) -> dict[str, Any]:
        prefix = payload.get("path_prefix") or ""
        paths = sorted(
            p
            for p in self.files
            if p == prefix or p.startswith(prefix.rstrip("/") + "/")
        )
        if prefix and not paths:
            return {"status": "refused", "reason": "not_found"}
        start = int(payload.get("continuation") or 0)
        size = payload["page_size"]
        chunk = paths[start : start + size]
        return {
            "status": "ok",
            "result": {
                "revision": self.revision,
                "entries": [
                    {
                        "path": p,
                        "mode": "100644",
                        "digest": hashlib.sha256(self.files[p]).hexdigest(),
                        "size": len(self.files[p]),
                    }
                    for p in chunk
                ],
                "continuation": str(start + size)
                if start + size < len(paths)
                else None,
            },
        }

    def blob(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.blob_reads += 1
        data = self.files.get(payload["path"])
        if data is None:
            return {"status": "refused", "reason": "not_found"}
        return {
            "status": "ok",
            "result": {
                "revision": self.revision,
                "content_base64": base64.b64encode(data).decode(),
            },
        }

    def commit(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload["base_revision"] != self.revision:
            return {"status": "refused", "reason": "conflict"}
        for change in payload["changes"]:
            if change["operation"] == "put":
                self.files[change["path"]] = base64.b64decode(change["content_base64"])
            else:
                self.files.pop(change["path"], None)
        self.commits.append(payload)
        self.revision = f"r{len(self.commits) + 1}"
        return {
            "status": "ok",
            "result": {
                "revision": self.revision,
                "receipt_ref": f"receipt:{payload['operation_id']}",
                "outcomes": [
                    {"path": c["path"], "outcome": "applied"}
                    for c in payload["changes"]
                ],
            },
        }

    async def call(self, operation: str, payload: Any) -> dict[str, Any]:
        return getattr(self, operation)(dict(payload))
