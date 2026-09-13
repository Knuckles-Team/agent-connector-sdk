"""Serve the freshrss-agent fixture over stdio for the command-line tests."""

from __future__ import annotations

from fleet_fixtures import FakeFreshRss, build_freshrss_server, freshrss_items

if __name__ == "__main__":
    build_freshrss_server(FakeFreshRss(freshrss_items(0, 5))).run(
        transport="stdio", show_banner=False
    )
