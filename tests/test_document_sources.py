"""Document sources moved from agent-utilities: git-markdown domain packs,
filesystem polling, governed ingest and external ACL sync.

Functional tests commit through :class:`KnowledgeIngest` into the SDK's
:class:`InMemorySink`, which validates every generated ``SourceIngest`` request
and keeps the durable checkpoint with compare-and-set semantics. The
governance-failure test also runs against a real epistemic-graph server.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess  # nosec B404 - fixed git argv, test-only
from pathlib import Path
from typing import Any

import pytest
from live_engine import live_ingest  # noqa: F401 - pytest fixture

from scion_sdk.adapters.document_sources import (
    DocumentBatch,
    DomainPack,
    FilesystemDocumentSource,
    GitMarkdownDocumentSource,
    GovernanceRefusedError,
    access_properties,
    apply_access,
    ingest_documents,
)
from scion_sdk.contracts import CONNECTOR_UNCONFIGURED_MARKING, ExternalAccess
from scion_sdk.ingest.model import Document, IngestBinding
from scion_sdk.ingest.service import KnowledgeIngest
from scion_sdk.testing.sinks import InMemorySink

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
PILLARS = DomainPack("pillars", ("docs/pillars/*.md",), "pillar-doc")
SKILLS = DomainPack("skills", ("skills/*/SKILL.md",), "skill-doc")
SOURCE_ID = "document-sources-proof"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(  # nosec B603 - fixed argv
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout.strip()


@pytest.fixture
def corpora(tmp_path: Path) -> Path:
    repo = tmp_path / "corpora"
    (repo / "docs" / "pillars" / "deep").mkdir(parents=True)
    (repo / "skills" / "alpha").mkdir(parents=True)
    (repo / "docs" / "pillars" / "KG-1-Memory.md").write_text(
        "# KG-1 Memory\n\n**Pillar:** knowledge\n\nTiered memory keeps context.\n"
    )
    (repo / "docs" / "pillars" / "deep" / "KG-2-Retrieval.md").write_text(
        "# KG-2 Retrieval\n\nMemory-first retrieval answers from the graph.\n"
    )
    (repo / "skills" / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha-skill\nskill_type: skill\nconcepts:\n  - SK-1\n  - SK-2\n"
        "---\n\n# Alpha\n\nThe alpha skill drafts reports.\n"
    )
    (repo / "README.md").write_text("# not in any pack\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "proof@example.invalid")
    _git(repo, "config", "user.name", "document-sources-proof")
    _git(repo, "add", "--", "docs", "skills", "README.md")
    _git(repo, "commit", "-q", "-m", "snapshot")
    return repo


def _ingest() -> tuple[KnowledgeIngest, InMemorySink]:
    sink = InMemorySink()
    return KnowledgeIngest(sink), sink  # type: ignore[arg-type]


def _records(sink: InMemorySink) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for batch in sink.batches.values():
        for record in batch.records:
            # The payload's location fields pass the privacy guard; the
            # portable source reference travels in provenance.
            latest[record.record_id] = {
                **record.payload,
                "source_ref": record.provenance.source_uri,
            }
    return latest


def _by_relpath(sink: InMemorySink) -> dict[str, dict[str, Any]]:
    return {payload["relpath"]: payload for payload in _records(sink).values()}


def _sources(repo: Path, pack: DomainPack) -> GitMarkdownDocumentSource:
    return GitMarkdownDocumentSource(
        repo, pack, access=ExternalAccess.public(), source_id=SOURCE_ID
    )


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.37")
def test_two_domain_packs_ingested_with_lineage(corpora: Path) -> None:
    ingest, sink = _ingest()
    sha = _git(corpora, "rev-parse", "HEAD")

    async def run() -> None:
        for pack in (PILLARS, SKILLS):
            binding = IngestBinding(connector="docs-mcp", stream=pack.name)
            report = await ingest_documents(ingest, binding, _sources(corpora, pack))
            assert report.cursor_advanced and report.documents_failed == 0

    asyncio.run(run())
    docs = _by_relpath(sink)
    assert set(docs) == {
        "docs/pillars/KG-1-Memory.md",
        "docs/pillars/deep/KG-2-Retrieval.md",
        "skills/alpha/SKILL.md",
    }
    pillar = docs["docs/pillars/KG-1-Memory.md"]
    assert (pillar["corpus"], pillar["doc_type"], pillar["git_commit"]) == (
        "pillars",
        "pillar-doc",
        sha,
    )
    skill = docs["skills/alpha/SKILL.md"]
    assert (skill["corpus"], skill["doc_type"]) == ("skills", "skill-doc")
    assert skill["title"] == "alpha-skill"
    assert skill["conceptIds"] == "SK-1 SK-2"
    assert "skill_type: skill" in skill["text"]
    for payload in docs.values():
        assert _HEX64.match(payload["evidence_digest"])
        assert payload["source_ref"].endswith(f"?rev={sha}")
        assert "@" not in payload["source_ref"]
        assert str(corpora) not in repr(payload)
    statuses = [sink.statuses[("docs-mcp", name)] for name in ("pillars", "skills")]
    assert all(s.accepted_checkpoint.position["cursor"] == sha for s in statuses)


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.37")
def test_incremental_change_updates_only_the_touched_file(corpora: Path) -> None:
    ingest, sink = _ingest()
    binding = IngestBinding(connector="docs-mcp", stream="pillars")
    source = _sources(corpora, PILLARS)
    sha1 = _git(corpora, "rev-parse", "HEAD")
    first = asyncio.run(ingest_documents(ingest, binding, source))
    before = _by_relpath(sink)
    ids_before = {
        p: rid for rid, p in ((r, v["relpath"]) for r, v in _records(sink).items())
    }

    changed = corpora / "docs" / "pillars" / "KG-1-Memory.md"
    changed.write_text(changed.read_text() + "\n## Addendum\n\nDiff-based re-ingest.\n")
    _git(corpora, "rm", "-q", "--", "docs/pillars/deep/KG-2-Retrieval.md")
    _git(corpora, "add", "--", "docs/pillars/KG-1-Memory.md")
    _git(corpora, "commit", "-q", "-m", "touch one pillar")
    sha2 = _git(corpora, "rev-parse", "HEAD")
    second = asyncio.run(ingest_documents(ingest, binding, source))
    unchanged = asyncio.run(ingest_documents(ingest, binding, source))

    assert first.documents == 2
    assert (second.documents, second.withdrawn, second.cursor_advanced) == (1, 1, True)
    assert (unchanged.documents, unchanged.receipt) == (0, None)
    last = list(sink.batches.values())[-1]
    assert [r.payload["relpath"] for r in last.records] == [
        "docs/pillars/KG-1-Memory.md"
    ]
    assert last.records[0].record_id == ids_before["docs/pillars/KG-1-Memory.md"]
    assert last.records[0].payload["git_commit"] == sha2
    assert [w.entity.record_id for w in last.withdrawals] == [
        ids_before["docs/pillars/deep/KG-2-Retrieval.md"]
    ]
    assert before["docs/pillars/KG-1-Memory.md"]["git_commit"] == sha1


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.38")
def test_filesystem_connector_ingestion_live_path(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    (root / "a.md").write_text("# Title A\nalpha content about graphs.\n")
    (root / "sub" / "b.txt").write_text("beta content discussing retrieval.\n")
    (root / "c.bin").write_bytes(b"\x00binary")
    (root / ".hidden").mkdir()
    (root / ".hidden" / "x.md").write_text("hidden\n")
    outside = tmp_path / "outside.md"
    outside.write_text("outside the root\n")
    (root / "link.md").symlink_to(outside)
    ingest, sink = _ingest()
    binding = IngestBinding(connector="files-mcp", stream="files")
    source = FilesystemDocumentSource(
        root, access=ExternalAccess.public(), source_id="fs"
    )

    first = asyncio.run(ingest_documents(ingest, binding, source))
    second = asyncio.run(ingest_documents(ingest, binding, source))

    assert (first.documents, first.cursor_advanced) == (2, True)
    assert (second.documents, second.cursor_advanced, second.receipt) == (
        0,
        False,
        None,
    )
    docs = _by_relpath(sink)
    assert set(docs) == {"a.md", "sub/b.txt"}
    assert docs["a.md"]["doc_type"] == "md"
    assert all(re.search(r"\?rev=\d+$", d["source_ref"]) for d in docs.values())
    assert str(tmp_path) not in repr(sink.batches)
    os.utime(root / "a.md", ns=(10**19, 10**19))
    third = asyncio.run(ingest_documents(ingest, binding, source))
    assert third.documents == 1


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.15")
def test_connector_ingestion_syncs_external_acl(tmp_path: Path) -> None:
    (tmp_path / "secret.md").write_text("restricted content\n")
    restricted = ExternalAccess(
        group_ids=["eng"], read_roles=["auditor"], markings=["pii"]
    )
    ingest, sink = _ingest()
    binding = IngestBinding(connector="files-mcp", stream="acl")

    asyncio.run(
        ingest_documents(
            ingest, binding, FilesystemDocumentSource(tmp_path, access=restricted)
        )
    )
    quarantine = FilesystemDocumentSource(tmp_path).poll(None).documents[0]

    payload = _by_relpath(sink)["secret.md"]
    assert payload["access_public"] is False
    assert payload["access_read_roles"] == ["group:eng", "auditor"]
    assert payload["access_markings"] == ["pii"]
    assert quarantine.properties["access_markings"] == [CONNECTOR_UNCONFIGURED_MARKING]
    assert quarantine.properties["access_read_roles"] == []
    assert access_properties(ExternalAccess.public())["access_public"] is True
    assert str(tmp_path) not in repr(sink.batches)


class _OneDocument:
    kind = "synthetic"

    def poll(self, cursor: str | None) -> DocumentBatch:
        return DocumentBatch(
            documents=(
                Document(
                    "governed:opaque",
                    "Synthetic governed content for embedding.",
                    source_uri="external-source://synthetic/opaque?rev=v1",
                ),
            ),
            cursor="v1",
        )


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.39")
def test_governed_connector_applies_envelope_before_embedding() -> None:
    ingest, sink = _ingest()
    seen: list[str] = []

    def governance(document: Document) -> ExternalAccess:
        seen.append(document.id)
        return ExternalAccess(group_ids=["research"], markings=["retention-p30d"])

    report = asyncio.run(
        ingest_documents(
            ingest,
            IngestBinding(connector="gov-mcp", stream="docs"),
            _OneDocument(),
            governance=governance,
        )
    )

    assert (report.documents, report.documents_failed, report.cursor_advanced) == (
        1,
        0,
        True,
    )
    assert seen == ["governed:opaque"]
    (batch,) = sink.batches.values()
    assert batch.records[0].payload["access_markings"] == ["retention-p30d"]
    assert batch.records[0].payload["access_read_roles"] == ["group:research"]
    assert batch.provider_checkpoint.position["cursor"] == "v1"
    stamped = apply_access(
        batch_doc := _OneDocument().poll(None).documents[0], ExternalAccess.public()
    )
    assert stamped.properties["access_public"] is True and batch_doc.properties == {}


def _refuse(_document: Document) -> ExternalAccess:
    raise GovernanceRefusedError("no envelope")


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.39")
def test_governed_connector_failure_blocks_document_and_checkpoint() -> None:
    ingest, sink = _ingest()
    report = asyncio.run(
        ingest_documents(
            ingest,
            IngestBinding(connector="gov-mcp", stream="docs"),
            _OneDocument(),
            governance=_refuse,
        )
    )

    assert (report.documents, report.documents_failed) == (0, 1)
    assert (report.cursor_advanced, report.failures) == (False, ("governed:opaque",))
    assert sink.batches == {} and sink.statuses == {}


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.39")
def test_governance_failure_leaves_real_engine_checkpoint(
    live_ingest: KnowledgeIngest,  # noqa: F811 - pytest fixture
) -> None:
    binding = IngestBinding(connector="gov-mcp", stream="docs")

    async def run() -> tuple[Any, str | None]:
        report = await ingest_documents(
            live_ingest, binding, _OneDocument(), governance=_refuse
        )
        return report, await live_ingest.accepted_cursor(binding)

    report, cursor = asyncio.run(run())

    assert (report.documents, report.documents_failed, report.receipt) == (0, 1, None)
    assert cursor is None
