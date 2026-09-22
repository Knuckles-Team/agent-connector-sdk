"""The transport fails closed on inconsistent providers and engine results."""

from __future__ import annotations

import hashlib
from typing import Any, cast

import pytest
from epistemic_graph.client import EpistemicGraphClient
from epistemic_graph.generated.index_repository import (
    IndexRepositoryScope,
    IndexResult,
)

from agent_connector_sdk.repository import (
    RepositoryAuthentication,
    RepositoryRef,
    RepositoryRevision,
    RepositoryTransportError,
    RepositoryTreeEntry,
    RepositoryTreePage,
    index_repository,
)
from agent_connector_sdk.repository.identity import _git_blob_object_id

_CONTENT = b"def a():\n    return 1\n"
_BLOB = _git_blob_object_id(_CONTENT, width=40)


def _revision(commit: str = "a") -> RepositoryRevision:
    return RepositoryRevision(
        provider="git-forge",
        repository_id="team/project",
        revision_id=commit * 40,
        tree_id="b" * 40,
    )


class _Provider:
    name = "git-forge"
    repository_id = "team/project"
    authentication = RepositoryAuthentication(
        provider="git-forge",
        principal="service:repository-reader",
        mechanism="bearer",
        credential_reference_digest=f"sha256:{'d' * 64}",
    )

    def __init__(self, pages: list[RepositoryTreePage], refs: int = 1) -> None:
        self.pages = pages
        self.refs = tuple(
            RepositoryRef(name=f"refs/heads/b{index}", revision=_revision())
            for index in range(refs)
        )
        self.tree_calls: list[str | None] = []

    async def list_refs(self) -> tuple[RepositoryRef, ...]:
        return self.refs

    async def list_tree(
        self, revision: RepositoryRevision, *, cursor: str | None, page_size: int
    ) -> RepositoryTreePage:
        self.tree_calls.append(cursor)
        return self.pages[len(self.tree_calls) - 1]

    async def fetch_blob(self, revision: RepositoryRevision, blob_id: str) -> bytes:
        return _CONTENT


def _page(
    *paths: str, cursor: str | None = None, commit: str = "a"
) -> RepositoryTreePage:
    entries = tuple(RepositoryTreeEntry(path=path, blob_id=_BLOB) for path in paths)
    return RepositoryTreePage(
        revision=_revision(commit), entries=entries, next_cursor=cursor
    )


class _Graph:
    def __init__(self, rename: str | None = None) -> None:
        self.rename = rename
        self.calls = 0

    async def index_repository(
        self, files: list[tuple[str, bytes]], *, scope: IndexRepositoryScope
    ) -> IndexResult:
        self.calls += 1
        digest = f"sha256:{hashlib.sha256(_CONTENT).hexdigest()}"
        outcome = {
            "file_path": self.rename or files[0][0],
            "status": "success",
            "content_digest": digest,
            "parser_capability_digest": f"sha256:{'c' * 64}",
            "diagnostics": [],
        }
        counters = dict.fromkeys(
            ["symbols_extracted", "files_parsed", "calls_resolved", "calls_unresolved"],
            0,
        )
        counters |= dict.fromkeys(
            ["calls_scope_resolved", "calls_type_resolved", "inherits_edges"], 0
        )
        counters |= dict.fromkeys(
            [
                "realizes_edges",
                "similar_edges",
                "imports_resolved",
                "imports_unresolved",
            ],
            0,
        )
        payload: dict[str, Any] = {"nodes": [], "edges": [], "file_outcomes": [outcome]}
        return IndexResult.model_validate({**payload, **counters})


def _client(graph: _Graph) -> EpistemicGraphClient:
    return cast(EpistemicGraphClient, type("Client", (), {"graph": graph})())


async def test_paged_tree_is_walked_once_per_revision() -> None:
    provider = _Provider([_page("a.py", cursor="2"), _page("b.py")], refs=2)
    graph = _Graph()

    receipt = await index_repository(provider, _client(graph))

    assert provider.tree_calls == [None, "2"]
    assert receipt.provider_pages == 2
    assert receipt.blobs_fetched == 1
    assert graph.calls == 1


@pytest.mark.parametrize(
    ("pages", "message"),
    [
        ([_page("a.py", commit="c")], "changed immutable revision"),
        ([_page("a.py", cursor="x"), _page("a.py")], "repeated a repository path"),
        ([_page("a.py", cursor="x"), _page("b.py", cursor="x")], "cursor repeated"),
    ],
)
async def test_inconsistent_provider_pages_stop_the_run(
    pages: list[RepositoryTreePage], message: str
) -> None:
    graph = _Graph()
    with pytest.raises(RepositoryTransportError, match=message):
        await index_repository(_Provider(pages), _client(graph))
    assert graph.calls == 0


async def test_provider_authentication_must_match() -> None:
    provider = _Provider([_page("a.py")])
    provider.authentication = provider.authentication.model_copy(
        update={"provider": "other"}
    )
    with pytest.raises(RepositoryTransportError, match="authentication disagree"):
        await index_repository(provider, _client(_Graph()))


async def test_reordered_engine_outcomes_fail_closed() -> None:
    with pytest.raises(RepositoryTransportError, match="reordered"):
        await index_repository(_Provider([_page("a.py")]), _client(_Graph("z.py")))
