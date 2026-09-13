"""Serve the demo connector over stdio for the connector-certify tests.

``--require-credential NAME`` exits before serving unless ``NAME`` is set: the
shape of a connector that cannot list its tools without credentials.
``--without-reader`` serves a server with no ``demo_reader`` tool.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from fastmcp import FastMCP
from fixture_server import SERVER_NAME, SERVER_VERSION, build_reader_server


def _required_credential(argv: list[str]) -> str:
    if "--require-credential" not in argv:
        return ""
    return argv[argv.index("--require-credential") + 1]


def _server(argv: list[str]) -> FastMCP[Any]:
    if "--without-reader" in argv:
        return FastMCP(SERVER_NAME, version=SERVER_VERSION)
    return build_reader_server(with_content=False)


if __name__ == "__main__":
    credential = _required_credential(sys.argv)
    if credential and not os.environ.get(credential):
        sys.stderr.write(f"{credential} is not set; refusing to start\n")
        raise SystemExit(3)
    _server(sys.argv).run(transport="stdio", show_banner=False)
