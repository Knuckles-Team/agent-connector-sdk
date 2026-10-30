"""Unknown-length and interrupted document streams retain closed reasons."""

from __future__ import annotations

import hashlib
import os

import httpx
import pytest

from scion_sdk.adapters.paper_document_errors import DocumentRefusal
from scion_sdk.adapters.paper_download_http import _copy_response


class _Stream(httpx.AsyncByteStream):
    def __init__(self, *, truncated: bool) -> None:
        self.truncated = truncated

    async def __aiter__(self):
        yield b"ab"
        if self.truncated:
            raise httpx.RemoteProtocolError("private upstream detail")
        yield b"cdef"


@pytest.mark.parametrize(
    ("truncated", "reason"), [(False, "size_exceeded"), (True, "integrity_failed")]
)
async def test_stream_errors_are_closed_and_bounded(tmp_path, truncated, reason):
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://example.org/paper"),
        stream=_Stream(truncated=truncated),
    )
    fd = os.open(tmp_path / "partial", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with pytest.raises(DocumentRefusal, match=reason) as refused:
            await _copy_response(response, 3, fd=fd, digest=hashlib.sha256())
    finally:
        os.close(fd)
    assert "private upstream detail" not in str(refused.value)
    assert (tmp_path / "partial").read_bytes() == b"ab"
