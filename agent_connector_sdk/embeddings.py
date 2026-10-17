"""Client for an external embedding API a connector calls for its own store.

A connector that keeps vectors in an external store (Qdrant, pgvector, MongoDB
and the like) embeds text through an OpenAI-compatible or Ollama endpoint.
Content epistemic-graph ingests is embedded by epistemic-graph, not here.

Configuration is read at call time:

``EMBEDDING_PROVIDER``
    ``openai`` (default) or ``ollama``.
``EMBEDDING_MODEL``
    The model identifier; required.
``EMBEDDING_BASE_URL``
    The API root; required for ``ollama``, ``https://api.openai.com/v1`` otherwise.
``EMBEDDING_API_KEY_REF``
    A runtime secret reference (``env://`` or ``secret://``) for the bearer token.
``EMBEDDING_ALLOWED_PRIVATE_HOSTS``
    Comma list of hostnames that may resolve into private address space.
``EMBEDDING_ALLOW_PLAINTEXT``
    Permit ``http://`` to a non-loopback host (an in-cluster endpoint).
``EMBEDDING_TLS_PROFILE`` / ``EMBEDDING_TLS_PROFILE_REF``
    The TLS profile, resolved by :func:`agent_connector_sdk.tls.resolve.resolve_tls_profile`.

Every request is DNS-pinned and never follows redirects or uses a proxy.
"""

from __future__ import annotations

import json
import math
import threading
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from agent_connector_sdk.auth.static import BearerAuth
from agent_connector_sdk.config import csv_values, setting
from agent_connector_sdk.credentials.runtime_references import (
    resolve_runtime_secret_reference,
)
from agent_connector_sdk.http.client import create_http_client
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.tls.resolve import resolve_tls_profile

__all__ = [
    "PROVIDERS",
    "EmbeddingModel",
    "EmbeddingSettings",
    "clear_embedding_model_cache",
    "create_embedding_model",
]

#: Providers this client speaks to.
PROVIDERS = ("openai", "ollama")
_OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_MAX_TIMEOUT_SECONDS = 3_600.0

EmbedFn = Callable[[httpx.Client, list[str], str], list[list[float]]]


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code >= 400:
        # The body may echo request text or provider detail; never surface it.
        raise ValueError(f"embedding request failed with HTTP {response.status_code}")


def _openai_embed(
    client: httpx.Client, texts: list[str], model: str
) -> list[list[float]]:
    response = client.post("embeddings", json={"model": model, "input": texts})
    _raise_for_status(response)
    rows = response.json()["data"]
    return [row["embedding"] for row in sorted(rows, key=lambda row: row["index"])]


def _ollama_embed(
    client: httpx.Client, texts: list[str], model: str
) -> list[list[float]]:
    response = client.post("api/embed", json={"model": model, "input": texts})
    _raise_for_status(response)
    embeddings = response.json().get("embeddings")
    if embeddings is None:
        raise ValueError("Ollama embeddings response is missing 'embeddings'")
    return [[float(value) for value in vector] for vector in embeddings]


_EMBED_FNS: dict[str, EmbedFn] = {"openai": _openai_embed, "ollama": _ollama_embed}


class EmbeddingModel:
    """Embeds text through one configured endpoint, in sub-batches.

    ``embed_batch_size`` may be raised by a caller before a bulk embed.
    """

    def __init__(
        self,
        model_name: str,
        client: httpx.Client,
        embed_fn: EmbedFn,
        embed_batch_size: int = 10,
    ) -> None:
        self.model_name = model_name
        self.embed_batch_size = embed_batch_size
        self._client = client
        self._embed_fn = embed_fn

    def get_text_embedding(self, text: str) -> list[float]:
        """The embedding of one document text."""
        return self.get_text_embedding_batch([text])[0]

    def get_query_embedding(self, query: str) -> list[float]:
        """The embedding of one query text."""
        return self.get_text_embedding(query)

    def get_text_embedding_batch(self, texts: list[str]) -> list[list[float]]:
        """The embeddings of ``texts``, in order."""
        out: list[list[float]] = []
        step = max(1, self.embed_batch_size)
        for start in range(0, len(texts), step):
            batch = texts[start : start + step]
            vectors = self._embed_fn(self._client, batch, self.model_name)
            if len(vectors) != len(batch):
                raise ValueError("embedding response does not match the request size")
            out.extend([float(value) for value in vector] for vector in vectors)
        return out


@dataclass(frozen=True)
class EmbeddingSettings:
    """One resolved embedding endpoint; the API key only by reference."""

    provider: str
    model: str
    base_url: str
    api_key_ref: str = ""
    allowed_private_hosts: tuple[str, ...] = ()
    allow_plaintext: bool = False
    timeout: float = 300.0

    def __post_init__(self) -> None:
        if self.provider not in PROVIDERS:
            raise ValueError(f"unsupported embedding provider: {self.provider}")
        if not self.model:
            raise ValueError("no embedding model is configured; set EMBEDDING_MODEL")
        if not self.base_url:
            raise ValueError("the embedding endpoint is not configured")
        timeout = self.timeout
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int | float)
            or not math.isfinite(float(timeout))
            or not 0 < float(timeout) <= _MAX_TIMEOUT_SECONDS
        ):
            raise ValueError("embedding timeout must be finite and in (0, 3600]")

    @classmethod
    def resolve(
        cls,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key_ref: str | None = None,
        timeout: float = 300.0,
    ) -> EmbeddingSettings:
        """Explicit arguments over ``EMBEDDING_*`` settings."""
        chosen = (provider or str(setting("EMBEDDING_PROVIDER", "openai"))).lower()
        url = base_url or str(setting("EMBEDDING_BASE_URL", ""))
        if not url and chosen == "openai":
            url = _OPENAI_DEFAULT_BASE_URL
        return cls(
            provider=chosen,
            model=model or str(setting("EMBEDDING_MODEL", "")),
            base_url=url,
            api_key_ref=api_key_ref or str(setting("EMBEDDING_API_KEY_REF", "")),
            allowed_private_hosts=tuple(
                csv_values(setting("EMBEDDING_ALLOWED_PRIVATE_HOSTS", ""))
            ),
            allow_plaintext=bool(setting("EMBEDDING_ALLOW_PLAINTEXT", False)),
            timeout=timeout,
        )

    def cache_key(self) -> str:
        return json.dumps(
            [
                self.provider,
                self.model,
                self.base_url,
                self.api_key_ref,
                list(self.allowed_private_hosts),
                self.allow_plaintext,
                float(self.timeout),
            ]
        )


_CACHE: dict[str, EmbeddingModel] = {}
_LOCK = threading.Lock()


def clear_embedding_model_cache() -> None:
    """Drop every cached client; the next call rebuilds it."""
    with _LOCK:
        _CACHE.clear()


def _build(
    settings: EmbeddingSettings, transport: httpx.BaseTransport | None
) -> EmbeddingModel:
    if settings.provider == "openai" and not settings.api_key_ref:
        raise ValueError(
            "the OpenAI-compatible embedding provider requires EMBEDDING_API_KEY_REF"
        )
    auth = (
        BearerAuth(resolve_runtime_secret_reference(settings.api_key_ref))
        if settings.api_key_ref
        else None
    )
    tls = resolve_tls_profile("embedding")
    options = HttpClientOptions(
        base_url=settings.base_url.rstrip("/") + "/",
        timeout=settings.timeout,
        tls=tls,
        auth=auth,
        pin_egress=transport is None,
        allowed_private_hosts=settings.allowed_private_hosts
        if transport is None
        else (),
        allow_plaintext=settings.allow_plaintext,
    )
    client = create_http_client(options, transport=transport)
    return EmbeddingModel(settings.model, client, _EMBED_FNS[settings.provider])


def create_embedding_model(
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key_ref: str | None = None,
    timeout: float = 300.0,
    *,
    transport: httpx.BaseTransport | None = None,
) -> EmbeddingModel:
    """A cached embedding client for the resolved endpoint.

    ``transport`` replaces the network transport (tests); such a client is
    not cached and not DNS-pinned.

    Raises:
        ValueError: the provider, model, endpoint, credentials or timeout is invalid.
    """
    settings = EmbeddingSettings.resolve(
        provider, model, base_url, api_key_ref, timeout
    )
    if transport is not None:
        return _build(settings, transport)
    key = settings.cache_key()
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is None:
            cached = _build(settings, None)
            _CACHE[key] = cached
        return cached
