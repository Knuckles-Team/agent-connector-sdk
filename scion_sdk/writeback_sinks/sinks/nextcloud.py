"""Nextcloud write-back sink (CONCEPT:AU-KG.ingest.enterprise-source-extractor).

Backfeeds the KG into Nextcloud — schedules calendar events from inferences
(e.g. a review when a TRM end-of-life approaches, or a change window from a
process) and publishes KG reports as files — fail-closed (``NEXTCLOUD_ENABLE_WRITE``),
dry-run-first. Uses the ``nextcloud-agent`` client (``create_calendar_event`` /
``write_file``).
"""

from __future__ import annotations

import logging
from typing import Any, cast

from ..core import (
    WritebackClientMixin,
    WritebackInvocation,
    WritebackResult,
    register_sink,
)

logger = logging.getLogger(__name__)


def _ics(uid: str, summary: str, *, start: str | None, end: str | None) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//agent-utilities//KG//EN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"SUMMARY:{summary}",
    ]
    if start:
        lines.append(f"DTSTART:{start}")
    if end:
        lines.append(f"DTEND:{end}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines)


class NextcloudSink(WritebackClientMixin):
    """Write-back sink for Nextcloud calendar + files."""

    domain = "nextcloud"
    enable_flag = "NEXTCLOUD_ENABLE_WRITE"
    client_module = "nextcloud_agent"
    client_label = "nextcloud"

    def _calendar_url(self, client: Any, ops: dict[str, Any]) -> str | None:
        if ops.get("calendar_url"):
            return cast("str | None", ops["calendar_url"])
        try:
            cals = client.list_calendars() or []
            if cals:
                return cast("str | None", cals[0].get("url") or cals[0].get("href"))
        except Exception:
            return None
        return None

    def _run(self, invocation: WritebackInvocation) -> WritebackResult:
        _, ops, client, result, dry_run = invocation.unpack()
        cal_url: str | None = None
        for c in ops.get("creations") or []:
            name = c.get("name")
            if not name:
                continue
            if dry_run:
                result.proposals.append(
                    {"op": "create_calendar_event", "summary": name}
                )
                continue
            cal_url = cal_url or self._calendar_url(client, ops)
            self._create_event(client, result, c, name, cal_url)
        for item in ops.get("enrichments") or []:
            self._publish_file(client, result, item, dry_run=dry_run)
        return result

    @staticmethod
    def _create_event(
        client: Any,
        result: WritebackResult,
        c: dict[str, Any],
        name: str,
        cal_url: str | None,
    ) -> None:
        if not cal_url:
            result.skipped += 1
            return
        try:
            uid = c.get("node") or name
            ics = _ics(str(uid), name, start=c.get("start"), end=c.get("end"))
            client.create_calendar_event(cal_url, ics)
            result.created += 1
        except Exception:
            logger.debug("nextcloud create_calendar_event failed", exc_info=True)
            result.errors += 1

    @staticmethod
    def _publish_file(
        client: Any, result: WritebackResult, item: dict[str, Any], *, dry_run: bool
    ) -> None:
        """Publish a KG report/file ({path, content})."""
        path = item.get("path")
        content = item.get("content")
        if not (path and content is not None):
            result.skipped += 1
            return
        if dry_run:
            result.proposals.append({"op": "write_file", "path": path})
            return
        try:
            client.write_file(path, content)
            result.enriched += 1
        except Exception:
            logger.debug("nextcloud write_file failed", exc_info=True)
            result.errors += 1


register_sink(NextcloudSink())
