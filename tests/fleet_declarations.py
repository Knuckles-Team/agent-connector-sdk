"""Declarations the freshrss-agent and archivebox-api fixture servers serve at
``connector://resources``."""

from __future__ import annotations

from typing import Any

DECLARATIONS: dict[str, dict[str, Any]] = {
    "freshrss-agent": {
        "connector": "freshrss-agent",
        "sources": [
            {
                "source_id": "freshrss",
                "record_type": "news_article",
                "tools": ["freshrss_reader"],
                "id_field": "id",
                "server": "freshrss-mcp",
                "preset": {
                    "action": "stream_contents",
                    "cursor_param": "continuation",
                    "cursor_path": "continuation",
                    "doc_type": "news_article",
                    "id_field": "id",
                    "pagination": "cursor",
                    "params": {"count": 100, "order": "o"},
                    "params_style": "json",
                    "records_path": "items",
                    "server": "freshrss-mcp",
                    "text_field": "text",
                    "title_field": "title",
                    "tool": "freshrss_reader",
                    "updated_field": "published",
                    "updated_since_param": "newer_than",
                },
            }
        ],
        "schema_mappings": {"news_article": {"ontology_class": "NewsArticle"}},
        "resources": [],
    },
    "archivebox-api": {
        "connector": "archivebox-api",
        "sources": [
            {
                "source_id": "archivebox-snapshots",
                "record_type": "web_snapshot",
                "tools": ["archivebox_core"],
                "id_field": "abid",
                "server": "archivebox-mcp",
                "preset": {
                    "action": "get_snapshots",
                    "doc_type": "web_snapshot",
                    "id_field": "abid",
                    "page_kind": "number",
                    "page_param": "page",
                    "page_size_param": "limit",
                    "pagination": "page",
                    "records_path": "items",
                    "server": "archivebox-mcp",
                    "text_field": "title",
                    "title_field": "url",
                    "tool": "archivebox_core",
                    "updated_field": "modified_at",
                },
            }
        ],
        "schema_mappings": {"web_snapshot": {"ontology_class": "WebSnapshot"}},
        "resources": [],
    },
}
