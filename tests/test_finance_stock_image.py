"""Generated stock images are original, deterministic and explicitly labeled."""

import hashlib
from xml.etree import ElementTree

import pytest

from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.finance.stock_image import (
    GeneratedStockImage,
    generate_stock_image,
)
from agent_connector_sdk.finance.stock_source import StockSourceAdapter, StockSourceKind
from agent_connector_sdk.manifest.presets import ToolPreset


@pytest.mark.spec("SCION-FINANCE-SOURCES-R002.1")
def test_stock_adapter_returns_generated_nonofficial_image():
    preset = ToolPreset(
        name="stock", server="finance", tool="read", id_field="record_id"
    )
    source = McpToolSourceAdapter(
        preset,
        connector="finance",
        mapping_reference="connector:finance#mappings/Record",
    )
    adapter = StockSourceAdapter(
        source, stock_kind=StockSourceKind.PROFILE, symbol="AAPL"
    )
    image = adapter.generated_image()
    assert isinstance(image, GeneratedStockImage)
    assert image == generate_stock_image("AAPL")
    assert image.symbol == "AAPL"
    assert image.media_type == "image/svg+xml"
    assert image.provenance == "scion-sdk:generated-stock-image:v1"
    assert image.official_logo is False
    assert image.sha256 == hashlib.sha256(image.content).hexdigest()
    root = ElementTree.fromstring(image.content)
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert "Generated illustration for AAPL" in image.content.decode()
    assert image.content != generate_stock_image("MSFT").content
    assert b"<script" not in image.content
    assert b"href=" not in image.content


@pytest.mark.parametrize(
    "symbol", ["", "aapl", "A/B", "<svg>", 'A" onclick=', "A" * 21, "Ω"]
)
def test_generated_image_rejects_unsafe_or_noncanonical_symbols(symbol):
    with pytest.raises(ValueError):
        generate_stock_image(symbol)
