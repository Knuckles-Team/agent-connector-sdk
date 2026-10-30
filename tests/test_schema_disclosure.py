"""Public SDK schema contract: exact bounded transport and refusal controls."""

import copy
import hashlib
import json

import pytest

from scion_sdk.mcp import schema_disclosure as fragments


def encoded(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


@pytest.fixture
def disclosure():
    schema = {"type": "string", "pattern": "[À-ž𐀀-𞤿]" * 6000}
    return fragments.build_schema_disclosure(
        (schema, {"type": "null"}),
        operation="unicodeInput",
        alias="fixture",
        source_sha256="a" * 64,
    )


def retrieved(disclosure):
    manifest, parts = disclosure.manifest.model_dump(), disclosure.parts
    return [
        fragments.read_schema_fragment(
            disclosure, index, expected_sha256=manifest["schema_sha256"]
        )
        for index in range(len(parts))
    ]


def test_large_unicode_schema_roundtrip_is_exact_and_bounded(disclosure):
    assert isinstance(disclosure, fragments.SchemaDisclosure)
    manifest = disclosure.manifest.model_dump()
    assert manifest["schema_bytes"] > 32 * 1024
    parts = retrieved(disclosure)
    assert all(len(encoded(part)) <= 32 * 1024 for part in parts)
    rebuilt = fragments.reconstruct_schema(manifest, parts)
    assert rebuilt["inputSchema"]["pattern"] == "[À-ž𐀀-𞤿]" * 6000
    assert digest(encoded(rebuilt)) == manifest["schema_sha256"]


@pytest.mark.parametrize("index", [-1, True, 1.0, "1", 100000])
def test_invalid_fragment_index_refuses(disclosure, index):
    with pytest.raises(ValueError, match="index"):
        fragments.read_schema_fragment(
            disclosure,
            index,
            expected_sha256=disclosure.manifest.model_dump()["schema_sha256"],
        )


def test_stale_selected_digest_refuses(disclosure):
    with pytest.raises(ValueError, match="Stale"):
        fragments.read_schema_fragment(disclosure, 0, expected_sha256="0" * 64)


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "duplicate",
        "reordered",
        "text",
        "operation",
        "manifest",
        "version_type",
        "extra",
    ],
)
def test_incomplete_or_changed_fragments_refuse(disclosure, damage):
    manifest = copy.deepcopy(disclosure.manifest.model_dump())
    parts = retrieved(disclosure)
    if damage == "missing":
        parts.pop()
    elif damage == "duplicate":
        parts[1] = parts[0]
    elif damage == "reordered":
        parts.reverse()
    elif damage == "text":
        parts[0]["text"] = "corrupt"
    elif damage == "operation":
        parts[0]["operation"] = "differentOperation"
    elif damage == "manifest":
        manifest["schema_sha256"] = "0" * 64
    elif damage == "version_type":
        parts[0]["version"] = True
    else:
        parts[0]["undeclared"] = 1
    with pytest.raises(ValueError):
        fragments.reconstruct_schema(manifest, parts)


def test_fragment_and_manifest_bounds_refuse(disclosure):
    manifest = copy.deepcopy(disclosure.manifest.model_dump())
    manifest["fragment_count"] = 1000000
    with pytest.raises(ValueError, match="fragment_count"):
        fragments.reconstruct_schema(manifest, [])
    parts = retrieved(disclosure)
    parts[0]["text"] = "x" * (fragments.CHUNK_BYTES + 1)
    with pytest.raises(ValueError, match=r"text|bounds"):
        fragments.reconstruct_schema(disclosure.manifest.model_dump(), parts)
