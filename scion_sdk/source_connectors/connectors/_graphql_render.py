"""Privacy-gated document rendering for the GraphQL document connector."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from scion_sdk.data_prep._classification import DataClassification
from scion_sdk.privacy import PersistencePrivacyGuard

from ..base import ExternalAccess, SourceDocument
from ._graphql_paths import _dig
from ._graphql_values import _digest, _private_digest, _safe_document_type

#: Resolved governance: access, classification, retention, legal hold, tenant,
#: schema version and ontology mapping version.
_Governance = tuple[ExternalAccess, DataClassification, str | None, bool, str, str, str]


@dataclass(frozen=True)
class _RenderedBody:
    raw_id: Any
    title: str
    text: str
    reports: list[Any]


@dataclass(frozen=True)
class _Digests:
    document_id: str
    content_digest: str
    version_digest: str
    detected: list[str]
    redactions: int


@dataclass(frozen=True)
class _GovernedFields:
    access: ExternalAccess
    classification: DataClassification
    retention: str | None
    legal_hold: bool


def _frontmatter_lines(
    privacy: PersistencePrivacyGuard, frontmatter: Any
) -> tuple[list[str], Any]:
    if frontmatter in (None, "", {}, []):
        return [], None
    clean, report = privacy.sanitize(frontmatter)
    if isinstance(clean, str):
        return ["", clean], report
    rendered = json.dumps(clean, sort_keys=True, ensure_ascii=False, default=str)
    return ["", rendered], report


def _section_level(section: dict[str, Any], level_field: str) -> int:
    try:
        return max(2, min(int(section.get(level_field) or 2) + 1, 6))
    except (TypeError, ValueError):
        return 2


@dataclass(frozen=True)
class _DocumentRenderer:
    """Render one mapped record as a sanitized, digest-stamped document."""

    privacy: PersistencePrivacyGuard
    max_sections: int
    max_content_chars: int
    source_alias: str
    operation: str
    external_access: ExternalAccess

    def _title(
        self, record: dict[str, Any], operation: dict[str, Any], raw_id: Any
    ) -> tuple[str, Any]:
        raw_title = _dig(record, str(operation.get("title_path") or "title"), raw_id)
        return self.privacy.sanitize_text(str(raw_title))

    def _content_lines(
        self, record: dict[str, Any], operation: dict[str, Any]
    ) -> tuple[list[str], Any]:
        content_path = str(operation.get("content_path") or "")
        if not content_path:
            return [], None
        clean_content, content_report = self.privacy.sanitize_text(
            str(_dig(record, content_path, "") or "")
        )
        lines: list[str] = []
        if clean_content.strip():
            lines = ["", clean_content.strip()]
        return lines, content_report

    def _one_section(
        self, section: Any, operation: dict[str, Any]
    ) -> tuple[list[str] | None, Any]:
        if not isinstance(section, dict):
            return None, None
        clean_section, report = self.privacy.sanitize(section)
        if not isinstance(clean_section, dict):
            return None, report
        title = str(
            clean_section.get(str(operation.get("section_title_field") or "title"))
            or "Section"
        )
        level = _section_level(
            clean_section, str(operation.get("section_level_field") or "level")
        )
        content = str(
            clean_section.get(str(operation.get("section_content_field") or "content"))
            or ""
        ).strip()
        lines = ["", f"{'#' * level} {title}"]
        if content:
            lines.extend(["", content])
        return lines, report

    def _sections(
        self, sections: list[Any], operation: dict[str, Any]
    ) -> tuple[list[str], list[Any]]:
        lines: list[str] = []
        reports: list[Any] = []
        for section in sections[: self.max_sections]:
            section_lines, report = self._one_section(section, operation)
            if report is not None:
                reports.append(report)
            if section_lines is not None:
                lines.extend(section_lines)
        return lines, reports

    def _body(
        self, record: dict[str, Any], operation: dict[str, Any]
    ) -> _RenderedBody | None:
        raw_id = _dig(record, str(operation.get("id_path") or "id"))
        if raw_id in (None, ""):
            return None
        frontmatter = _dig(
            record,
            str(operation.get("frontmatter_path") or "document.frontmatter"),
            None,
        )
        sections = _dig(
            record, str(operation.get("sections_path") or "document.sections"), []
        )
        title, title_report = self._title(record, operation, raw_id)
        parts = [
            ([f"# {title}"], title_report),
            self._content_lines(record, operation),
            _frontmatter_lines(self.privacy, frontmatter),
        ]
        section_lines, section_reports = self._sections(
            sections if isinstance(sections, list) else [], operation
        )
        body = [line for lines, _ in parts for line in lines] + section_lines
        reports = [report for _, report in parts if report is not None]
        text = "\n".join(body)[: self.max_content_chars].strip()
        if not text:
            return None
        return _RenderedBody(raw_id, title, text, [*reports, *section_reports])

    def _digests(
        self,
        record: dict[str, Any],
        operation: dict[str, Any],
        identity_key: str,
        rendered: _RenderedBody,
    ) -> _Digests:
        document_id = _private_digest(
            identity_key,
            self.source_alias,
            self.operation,
            "document",
            str(rendered.raw_id),
        )
        updated_path = str(operation.get("updated_path") or "")
        raw_updated = _dig(record, updated_path) if updated_path else None
        clean_updated, updated_report = self.privacy.sanitize_text(
            str(raw_updated or "")
        )
        reports = [*rendered.reports, updated_report]
        content_digest = _digest(rendered.text)
        version_digest = _private_digest(
            identity_key,
            self.source_alias,
            self.operation,
            "document-version",
            str(rendered.raw_id),
            clean_updated or content_digest,
        )
        return _Digests(
            document_id,
            content_digest,
            version_digest,
            sorted({item for report in reports for item in report.detected_types}),
            sum(report.redactions for report in reports),
        )

    def _governed_fields(self, governance: _Governance | None) -> _GovernedFields:
        if governance is None:
            return _GovernedFields(
                self.external_access, DataClassification.INTERNAL, None, False
            )
        return _GovernedFields(*governance[:4])

    def render_document(
        self,
        record: dict[str, Any],
        operation: dict[str, Any],
        identity_key: str,
        *,
        profile_digest: str = "",
        entity_id: str | None = None,
        governance: _Governance | None = None,
    ) -> SourceDocument | None:
        rendered = self._body(record, operation)
        if rendered is None:
            return None
        digests = self._digests(record, operation, identity_key, rendered)
        governed = self._governed_fields(governance)
        document_id = digests.document_id
        governed_entity_id = entity_id or (
            f"doc:graphql_document:{hashlib.sha256(document_id.encode('utf-8')).hexdigest()[:24]}"
        )
        return SourceDocument(
            id=document_id,
            source_uri=f"external-source://{self.source_alias}/{document_id}",
            title=rendered.title,
            text=rendered.text,
            doc_type=_safe_document_type(operation.get("doc_type")),
            metadata={
                "source_alias": self.source_alias,
                "source_kind": "graphql",
                "operation": self.operation,
                "governed_entity_id": governed_entity_id,
                "profile_digest": profile_digest,
                "content_digest": digests.content_digest,
                "classification": governed.classification.value,
                "retention": governed.retention,
                "legal_hold": governed.legal_hold,
                "embedding_handoff": True,
                "privacy": {
                    "redactions": digests.redactions,
                    "detected_types": digests.detected,
                },
            },
            external_access=governed.access,
            updated_at=digests.version_digest,
        )
