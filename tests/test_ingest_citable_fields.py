"""Citable public URLs survive the persistence guard (SCION-SOURCE-INGEST-R004.26)."""

from __future__ import annotations

import pytest

from scion_sdk.ingest import ChangeSet, Document, IngestBinding
from scion_sdk.ingest.request import build_request
from scion_sdk.privacy import PersistencePrivacyGuard, public_http_url

PAGE = "https://kubernetes.io/docs/concepts/workloads/pods/disruptions/"


def _payload(binding: IngestBinding, source_uri: str) -> dict:
    request = build_request(
        binding,
        ChangeSet(
            documents=(
                Document(
                    id="web:1",
                    text="A pod disruption budget limits evictions.",
                    title="PDB",
                    source_uri=source_uri,
                    properties={
                        "canonical_url": source_uri,
                        "endpoint_url": source_uri,
                    },
                ),
            )
        ),
        previous=None,
    )
    return dict(request.records[0].payload)


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.26")
def test_citable_fields_keep_public_urls_and_nothing_else() -> None:
    binding = IngestBinding(
        connector="webarchiver-mcp",
        stream="web_page",
        citable_fields=frozenset({"source_uri", "canonical_url"}),
    )
    payload = _payload(binding, PAGE)
    assert payload["source_uri"] == PAGE
    assert payload["canonical_url"] == PAGE
    # A location field the binding does not cite stays redacted.
    assert payload["endpoint_url"] == "[REDACTED_LOCATION]"
    # The default binding still redacts every location field.
    default = _payload(
        IngestBinding(connector="webarchiver-mcp", stream="web_page"), PAGE
    )
    assert default["source_uri"] == "[REDACTED_LOCATION]"


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.26")
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/x",
        "http://10.0.0.5/x",
        "https://user:pw@example.org/x",  # sanitizer:ignore - synthetic credentialed URL proving redaction
        "http://intranet/x",
        "file:///etc/passwd",
        "ftp://example.org/x",
    ],
)
def test_a_non_public_url_stays_redacted_even_when_citable(url: str) -> None:
    assert not public_http_url(url)
    guard = PersistencePrivacyGuard(deny_terms=(), citable_fields={"source_uri"})
    clean, report = guard.sanitize({"source_uri": url})
    assert clean["source_uri"] != url
    assert report.redactions >= 1


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.26")
def test_public_http_url_accepts_public_hosts() -> None:
    assert public_http_url(PAGE)
    assert public_http_url("http://93.184.216.34/page")
