"""GraphQL document source: bounded, read-only, zero-PII and governed."""

from __future__ import annotations

import copy
import json
import socket
import ssl
from typing import Any

import pytest

pytest.importorskip("graphql")

from agent_connector_sdk.ingest.model import Entity, Withdrawal
from agent_connector_sdk.source_connectors import build_connector, http_safety
from agent_connector_sdk.source_connectors.connectors import graphql_document
from agent_connector_sdk.source_connectors.connectors.graphql_document import (
    GraphQLDocumentConnector,
    GraphQLDocumentError,
    GraphQLHierarchyBatch,
)

PROFILE_REF = "openbao://apps/knowledge-catalog#graphql"

DOCUMENT_PROFILE: dict[str, Any] = {
    "endpoint": "https://knowledge.example.test/graphql",
    "identity_hmac_key": "synthetic-test-key-material-32-bytes",
    "headers": {"Authorization": "Bearer synthetic-token"},
    "operations": {
        "entity_document": {
            "query": (
                "query EntityDocument($slug: String!) { entity(slug: $slug) { name "
                "slug document { title frontmatter sections { title level content } } } }"
            ),
            "root_path": "entity",
            "id_path": "slug",
            "title_path": "document.title",
            "frontmatter_path": "document.frontmatter",
            "sections_path": "document.sections",
        }
    },
}
DOCUMENT_PAYLOAD = {
    "data": {
        "entity": {
            "name": "Synthetic Lifecycle",
            "slug": "synthetic-lifecycle",
            "document": {
                "title": "Synthetic Lifecycle Guide",
                "frontmatter": {
                    "classification": "internal",
                    "created_by": "Example Person",
                },
                "sections": [
                    {
                        "title": "Overview",
                        "level": 1,
                        "content": "Contact contact@example.test. Local draft: "
                        "/home/example/private/draft.md",
                    }
                ],
            },
        }
    }
}

HIERARCHY_PROFILE: dict[str, Any] = {
    "endpoint": "https://hierarchy.example.test/graphql",
    "identity_hmac_key": "synthetic-hierarchy-key-material-32-bytes",
    "headers": {"Authorization": "Bearer synthetic-hierarchy-token"},
    "limits": {"max_pages": 4, "page_size": 2, "max_entities": 50, "max_documents": 10},
    "governance": {
        "classification": "confidential",
        "retention": "P30D",
        "legal_hold": False,
        "tenant": "synthetic-tenant",
        "schema_version": "2",
        "ontology_mapping_version": "synthetic-v1",
        "access": {
            "is_public": False,
            "group_ids": ["synthetic-readers"],
            "markings": ["synthetic-restricted"],
        },
    },
    "operations": {
        "hierarchy_sync": {
            "query": (
                "query Hierarchy($after: String, $first: Int!) { catalog(after: $after, "
                "first: $first) { units documents applications dependencies "
                "pageInfo { endCursor hasNextPage } } }"
            ),
            "root_path": "catalog",
            "snapshot_authoritative": True,
            "pagination": {
                "cursor_variable": "after",
                "page_size_variable": "first",
                "next_cursor_path": "catalog.pageInfo.endCursor",
                "has_more_path": "catalog.pageInfo.hasNextPage",
            },
            "mappings": {
                "hierarchy": {
                    "records_path": "units",
                    "id_path": "id",
                    "children_path": "children",
                    "version_path": "updated",
                    "property_allowlist": ["name"],
                    "entity_type": "HierarchyUnit",
                },
                "documents": {
                    "records_path": "documents",
                    "id_path": "id",
                    "version_path": "updated",
                    "title_path": "title",
                    "content_path": "content",
                    "parent_id_path": "unit_id",
                    "application_id_path": "application_id",
                    "property_allowlist": ["category"],
                    "doc_type": "hierarchy_document",
                },
                "applications": {
                    "records_path": "applications",
                    "id_path": "id",
                    "version_path": "updated",
                    "parent_id_path": "unit_id",
                    "property_allowlist": ["name", "runtime"],
                },
                "dependencies": {
                    "records_path": "dependencies",
                    "id_path": "id",
                    "version_path": "updated",
                    "source_id_path": "source_id",
                    "target_id_path": "target_id",
                    "property_allowlist": ["criticality"],
                },
            },
        }
    },
}


def _doc(i: str, unit: str, app: str) -> dict[str, str]:
    return {
        "id": f"doc-{i}",
        "title": f"Synthetic Guide {i}",
        "content": f"Bounded synthetic content {i}.",
        "category": "guide",
        "unit_id": unit,
        "application_id": app,
        "updated": "v1",
    }


def _app(i: str, unit: str) -> dict[str, str]:
    return {
        "id": f"app-{i}",
        "name": f"App {i}",
        "runtime": "synthetic",
        "unit_id": unit,
        "updated": "v1",
    }


def _pages() -> list[dict[str, Any]]:
    child = {"id": "unit-child", "name": "Child", "updated": "v1", "children": []}
    first = {
        "units": [
            {"id": "unit-root", "name": "Root", "updated": "v1", "children": [child]}
        ],
        "documents": [_doc("one", "unit-root", "app-one")],
        "applications": [_app("one", "unit-root")],
        "dependencies": [],
        "pageInfo": {"endCursor": "cursor-one", "hasNextPage": True},
    }
    second = {
        "units": [],
        "documents": [_doc("two", "unit-child", "app-two")],
        "applications": [_app("two", "unit-child")],
        "dependencies": [
            {
                "id": "dependency-one",
                "source_id": "app-one",
                "target_id": "app-two",
                "criticality": "synthetic",
                "updated": "v1",
            }
        ],
        "pageInfo": {"endCursor": None, "hasNextPage": False},
    }
    return [{"data": {"catalog": first}}, {"data": {"catalog": second}}]


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.content = json.dumps(payload).encode()
        self.headers = {"content-length": str(len(self.content))}

    def raise_for_status(self) -> None:
        return None


class _Transport:
    """Serves page ``n`` for the ``n``-th distinct cursor; records each request."""

    def __init__(self, *pages: dict[str, Any]) -> None:
        self.pages = list(pages)
        self.calls: list[dict[str, Any]] = []

    def post(self, endpoint: str, **kwargs: Any) -> _Response:
        self.calls.append({"endpoint": endpoint, **kwargs})
        cursor = kwargs["json"]["variables"].get("after")
        return _Response(self.pages[0 if cursor is None else 1])


def _connector(profile: dict[str, Any], transport: _Transport, **config: Any) -> Any:
    operation = next(iter(profile["operations"]))
    return build_connector(
        "graphql_document",
        {
            "source_alias": "synthetic-source",
            "operation": operation,
            "profile": profile,
            "transport": transport,
            **config,
        },
    )


def test_profile_must_be_secret_backed_reference() -> None:
    with pytest.raises(ValueError, match="profile_ref"):
        build_connector(
            "graphql_document",
            {
                "source_alias": "synthetic-source",
                "operation": "entity_document",
                "profile": DOCUMENT_PROFILE,
            },
        )


def test_document_is_redacted_and_carries_no_source_details() -> None:
    transport = _Transport(DOCUMENT_PAYLOAD)
    connector = build_connector(
        "graphql_document",
        {
            "source_alias": "knowledge-catalog",
            "operation": "entity_document",
            "variables": {"slug": "synthetic-lifecycle"},
            "profile_ref": PROFILE_REF,
            "profile_resolver": lambda _ref: json.dumps(DOCUMENT_PROFILE),
            "transport": transport,
        },
    )
    (doc,) = connector.load()
    assert doc.title == "Synthetic Lifecycle Guide"
    assert "contact@example.test" not in doc.text and "/home/example" not in doc.text
    assert doc.external_access.markings == ["connector-unconfigured-acl"]
    persisted = json.dumps(doc.model_dump(), sort_keys=True)
    for secret in (
        "knowledge.example.test",
        "synthetic-token",
        "key-material",
        "openbao://",
        "query EntityDocument",
    ):
        assert secret not in persisted
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer synthetic-token"
    assert "verify" not in transport.calls[0]


@pytest.mark.spec("SDK-SOURCE-INGEST-R901.3")
def test_default_graphql_wiring_uses_sdk_resolvers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = copy.deepcopy(DOCUMENT_PROFILE)
    profile["endpoint"] = "https://example.com/graphql"
    profile["transport_security"] = {"system_trust": True}
    monkeypatch.setenv("GRAPHQL_DOCUMENT_PROFILE", json.dumps(profile))

    credential_calls: list[tuple[str, object]] = []
    real_resolve_secret = graphql_document.resolve_secret_reference

    def resolve_secret(reference: str, resolver: object = None) -> str:
        credential_calls.append((reference, resolver))
        return real_resolve_secret(reference, resolver)

    monkeypatch.setattr(graphql_document, "resolve_secret_reference", resolve_secret)

    tls_calls: list[tuple[str, dict[str, object]]] = []
    real_resolve_tls = graphql_document.resolve_tls_profile

    def resolve_tls(service: str, **kwargs: object) -> object:
        tls_calls.append((service, kwargs))
        return real_resolve_tls(service, **kwargs)

    monkeypatch.setattr(graphql_document, "resolve_tls_profile", resolve_tls)

    safe_url_calls: list[tuple[str, dict[str, object]]] = []
    real_require_safe_url = graphql_document.require_safe_source_url

    def require_safe_url(url: str, **kwargs: object) -> str:
        safe_url_calls.append((url, kwargs))
        return real_require_safe_url(url, **kwargs)

    monkeypatch.setattr(graphql_document, "require_safe_source_url", require_safe_url)

    def fake_getaddrinfo(*_: object, **__: object) -> list[tuple[object, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(http_safety.socket, "getaddrinfo", fake_getaddrinfo)

    class _Response:
        def __init__(self) -> None:
            self._body = json.dumps(DOCUMENT_PAYLOAD).encode()
            self.headers = {"content-length": str(len(self._body))}

        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self) -> Any:
            return iter((self._body,))

    class _Stream:
        def __init__(self) -> None:
            self.response = _Response()

        def __enter__(self) -> _Response:
            return self.response

        def __exit__(self, *_: object) -> None:
            return None

    clients: list[object] = []

    class _Client:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            self.calls: list[dict[str, object]] = []
            clients.append(self)

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def stream(self, method: str, url: str, **kwargs: object) -> _Stream:
            self.calls.append({"method": method, "url": url, **kwargs})
            return _Stream()

    monkeypatch.setattr(graphql_document.httpx, "Client", _Client)
    connector = build_connector(
        "graphql_document",
        {
            "source_alias": "knowledge-catalog",
            "operation": "entity_document",
            "variables": {"slug": "synthetic-lifecycle"},
            "profile_ref": "env://GRAPHQL_DOCUMENT_PROFILE",
        },
    )

    (document,) = connector.load()

    assert document.title == "Synthetic Lifecycle Guide"
    assert credential_calls == [("env://GRAPHQL_DOCUMENT_PROFILE", None)]
    assert safe_url_calls[0][0] == profile["endpoint"]
    assert safe_url_calls[0][1]["resolve_dns"] is True
    assert tls_calls[0][0] == "GRAPHQL_DOCUMENT"
    assert tls_calls[0][1]["profile"] == {"system_trust": True}
    client = clients[0]
    assert isinstance(client.kwargs["verify"], ssl.SSLContext)
    assert client.kwargs["follow_redirects"] is False
    assert client.calls[0]["method"] == "POST"
    assert client.calls[0]["url"] == profile["endpoint"]
    assert client.calls[0]["headers"] == profile["headers"]


def _with(path: tuple[str, ...], value: Any) -> dict[str, Any]:
    profile = copy.deepcopy(DOCUMENT_PROFILE)
    target = profile
    for key in path[:-1]:
        target = target[key]
    if value is None:
        target.pop(path[-1])
    else:
        target[path[-1]] = value
    return profile


QUERY = ("operations", "entity_document", "query")


# spec: SDK-SOURCE-INGEST-R901.4
@pytest.mark.parametrize(
    ("profile", "payload", "match"),
    [
        (_with(("identity_hmac_key",), None), DOCUMENT_PAYLOAD, "identity HMAC"),
        (
            _with(("endpoint",), "https://127.0.0.1/graphql"),
            DOCUMENT_PAYLOAD,
            "not permitted",
        ),
        (
            _with(("headers",), {"X-A": "v\r\nInjected: v"}),
            DOCUMENT_PAYLOAD,
            "headers are invalid",
        ),
        (
            _with(("headers",), {"Proxy-Authorization": "v"}),
            DOCUMENT_PAYLOAD,
            "headers are invalid",
        ),
        (_with(QUERY, "mutation U { update { id } }"), DOCUMENT_PAYLOAD, None),
        (_with(QUERY, "subscription S { changed { id } }"), DOCUMENT_PAYLOAD, None),
        (
            _with(QUERY, "query I { __schema { queryType { name } } }"),
            DOCUMENT_PAYLOAD,
            None,
        ),
        (
            DOCUMENT_PROFILE,
            {"errors": [{"message": "leak contact@example.test"}]},
            "^GraphQL source returned an error$",
        ),
    ],
)
def test_unsafe_profiles_and_upstream_errors_are_refused(
    profile: dict[str, Any], payload: dict[str, Any], match: str | None
) -> None:
    with pytest.raises(GraphQLDocumentError, match=match):
        list(_connector(profile, _Transport(payload)).load())


# spec: SDK-SOURCE-INGEST-R901.6
@pytest.mark.spec("SDK-SOURCE-INGEST-R901.1")
def test_hierarchy_poll_emits_governed_entities_and_is_idempotent() -> None:
    transport = _Transport(*_pages())
    connector = _connector(HIERARCHY_PROFILE, transport)
    first = connector.poll()
    changes = connector.last_envelopes
    assert len(first.documents) == 2 and len(changes) == 7
    assert all(isinstance(change, Entity) for change in changes)
    props = [change.properties for change in changes]
    assert {p["classification"] for p in props} == {"confidential"}
    assert {p["retention"] for p in props} == {"P30D"}
    assert all(p["access_read_roles"] == ["group:synthetic-readers"] for p in props)
    dependency = next(p for p in props if p["entity_kind"] == "dependency")
    assert dependency["_links"][0]["type"] == "DEPENDS_ON"
    persisted = json.dumps([p for p in props], default=str)
    for private in (
        "unit-root",
        "doc-one",
        "app-two",
        "dependency-one",
        "key-material",
    ):
        assert private not in persisted
    assert [c["json"]["variables"] for c in transport.calls] == [
        {"after": None, "first": 2},
        {"after": "cursor-one", "first": 2},
    ]
    assert connector.poll(first.checkpoint).documents == []
    assert connector.last_envelopes == []


# spec: SDK-SOURCE-INGEST-R901.2
def test_authoritative_snapshot_withdraws_a_removed_record_once() -> None:
    pages = _pages()
    connector = _connector(HIERARCHY_PROFILE, _Transport(*pages))
    assert isinstance(connector, GraphQLDocumentConnector)
    initial = connector.poll_envelopes()
    assert isinstance(initial, GraphQLHierarchyBatch)
    pages[1]["data"]["catalog"]["documents"] = []
    reconciled = connector.poll_envelopes(initial.checkpoint)
    withdrawals = [c for c in reconciled.envelopes if isinstance(c, Withdrawal)]
    assert len(withdrawals) == 1
    assert withdrawals[0].id in {c.id for c in initial.envelopes}
    stable = connector.poll_envelopes(reconciled.checkpoint)
    assert not [c for c in stable.envelopes if isinstance(c, Withdrawal)]


def test_authoritative_empty_snapshot_needs_explicit_approval() -> None:
    transport = _Transport(*_pages())
    connector = _connector(HIERARCHY_PROFILE, transport)
    initial = connector.poll_envelopes()
    empty = {
        "units": [],
        "documents": [],
        "applications": [],
        "dependencies": [],
        "pageInfo": {"endCursor": None, "hasNextPage": False},
    }
    transport.pages[0] = {"data": {"catalog": empty}}
    with pytest.raises(GraphQLDocumentError, match="requires explicit approval"):
        connector.poll_envelopes(initial.checkpoint)


@pytest.mark.spec("SDK-SOURCE-INGEST-R901.5")
def test_dry_run_plan_reports_counts_only() -> None:
    connector = _connector(HIERARCHY_PROFILE, _Transport(*_pages()), dry_run=True)
    plan = connector.plan()
    assert plan["entity_counts"] == {
        "hierarchy": 2,
        "document": 2,
        "application": 2,
        "dependency": 1,
    }
    assert list(connector.load()) == [] and connector.last_envelopes == []
    assert "unit-root" not in json.dumps(plan) and "query Hierarchy" not in json.dumps(
        plan
    )


def test_missing_retention_governance_is_refused() -> None:
    profile = copy.deepcopy(HIERARCHY_PROFILE)
    profile["governance"].pop("retention")
    with pytest.raises(GraphQLDocumentError, match="retention policy"):
        _connector(profile, _Transport(*_pages())).plan()
