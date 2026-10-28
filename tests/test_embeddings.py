"""SDK-CONNECTOR-CONTROL-R014.22: external embedding API client."""

from __future__ import annotations

import json

import httpx
import pytest

from agent_connector_sdk import embeddings
from agent_connector_sdk.embeddings import (
    EmbeddingSettings,
    clear_embedding_model_cache,
    create_embedding_model,
)

pytestmark = pytest.mark.spec("SDK-CONNECTOR-CONTROL-R014.22")


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch):
    for key in (
        "EMBEDDING_PROVIDER",
        "EMBEDDING_MODEL",
        "EMBEDDING_BASE_URL",
        "EMBEDDING_API_KEY_REF",
        "EMBEDDING_ALLOWED_PRIVATE_HOSTS",
        "EMBEDDING_ALLOW_PLAINTEXT",
    ):
        monkeypatch.delenv(key, raising=False)
    clear_embedding_model_cache()
    yield
    clear_embedding_model_cache()


def _openai_transport(seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        rows = [
            {"index": index, "embedding": [float(len(text)), float(index)]}
            for index, text in enumerate(body["input"])
        ]
        return httpx.Response(200, json={"data": list(reversed(rows))})

    return httpx.MockTransport(handler)


def test_openai_embeds_in_batches_with_bearer_from_reference(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "nomic-embed")
    monkeypatch.setenv("EMBEDDING_API_KEY_REF", "env://EMBED_TOKEN")
    monkeypatch.setenv("EMBED_TOKEN", "s3cret")
    seen: list[httpx.Request] = []
    model = create_embedding_model(transport=_openai_transport(seen))
    model.embed_batch_size = 2

    vectors = model.get_text_embedding_batch(["a", "bb", "ccc"])

    assert vectors == [[1.0, 0.0], [2.0, 1.0], [3.0, 0.0]]
    assert len(seen) == 2
    assert str(seen[0].url) == "https://api.openai.com/v1/embeddings"
    assert seen[0].headers["Authorization"] == "Bearer s3cret"
    assert json.loads(seen[0].content)["model"] == "nomic-embed"
    assert model.get_query_embedding("dd") == [2.0, 0.0]


def test_ollama_endpoint_and_missing_embeddings_refused(monkeypatch):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(200, json={"embeddings": [[0.5]]})
        return httpx.Response(200, json={})

    model = create_embedding_model(
        provider="ollama",
        model="m",
        base_url="https://ollama.example.test",
        transport=httpx.MockTransport(handler),
    )
    assert model.get_text_embedding("x") == [0.5]
    assert calls[0] == "https://ollama.example.test/api/embed"
    with pytest.raises(ValueError, match="missing 'embeddings'"):
        model.get_text_embedding("y")


def test_http_error_never_echoes_body(monkeypatch):
    model = create_embedding_model(
        provider="ollama",
        model="m",
        base_url="https://ollama.example.test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(400, text="secret request text")
        ),
    )
    with pytest.raises(ValueError) as caught:
        model.get_text_embedding("x")
    assert "secret request text" not in str(caught.value)
    assert "HTTP 400" in str(caught.value)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"provider": "mock", "model": "m"}, "unsupported"),
        ({"provider": "openai"}, "EMBEDDING_MODEL"),
        ({"provider": "ollama", "model": "m"}, "not configured"),
        ({"provider": "openai", "model": "m", "timeout": 0}, "timeout"),
    ],
)
def test_invalid_settings_refused(kwargs, message):
    with pytest.raises(ValueError, match=message):
        EmbeddingSettings.resolve(**kwargs)


def test_openai_without_key_reference_refused():
    with pytest.raises(ValueError, match="EMBEDDING_API_KEY_REF"):
        create_embedding_model(provider="openai", model="m")


def test_client_is_cached_per_resolved_endpoint(monkeypatch):
    built: list[EmbeddingSettings] = []

    def fake_build(settings, transport):
        built.append(settings)
        return object()

    monkeypatch.setattr(embeddings, "_build", fake_build)
    first = create_embedding_model(provider="ollama", model="m", base_url="https://a")
    again = create_embedding_model(provider="ollama", model="m", base_url="https://a")
    other = create_embedding_model(provider="ollama", model="m", base_url="https://b")
    assert first is again and first is not other
    assert len(built) == 2


def test_real_client_is_dns_pinned_without_redirects(monkeypatch):
    monkeypatch.setenv("EMBEDDING_ALLOWED_PRIVATE_HOSTS", "ollama.example.test")
    model = create_embedding_model(
        provider="ollama", model="m", base_url="https://ollama.example.test"
    )
    client = model._client
    assert client.follow_redirects is False
    # The air-gap guard is outermost; DNS pinning must remain inside it.
    assert type(client._transport).__name__ == "_AirgapTransport"
    assert type(client._transport._inner).__name__ == "DnsPinnedEgressTransport"


def test_providers_and_model_type_are_the_public_surface(monkeypatch):
    from agent_connector_sdk.embeddings import PROVIDERS, EmbeddingModel

    assert PROVIDERS == ("openai", "ollama")
    monkeypatch.setenv("EMBEDDING_MODEL", "nomic-embed")
    monkeypatch.setenv("EMBEDDING_API_KEY_REF", "env://EMBED_TOKEN")
    monkeypatch.setenv("EMBED_TOKEN", "s3cret")
    model = create_embedding_model(transport=_openai_transport([]))
    assert isinstance(model, EmbeddingModel)
    with pytest.raises(ValueError):
        create_embedding_model(provider="not-a-provider")
