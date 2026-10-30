"""Wire formats of the supported embedding providers."""

from __future__ import annotations

from collections.abc import Callable

import httpx

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
