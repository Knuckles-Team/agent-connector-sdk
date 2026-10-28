"""Generate an original, symbol-specific stock illustration."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

__all__ = ["GeneratedStockImage", "generate_stock_image"]

_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.\-]{0,19}\Z", re.ASCII)


@dataclass(frozen=True, slots=True)
class GeneratedStockImage:
    """An original illustration, not a representation of a company logo."""

    symbol: str
    content: bytes
    sha256: str
    media_type: str = field(default="image/svg+xml", init=False)
    provenance: str = field(default="scion-sdk:generated-stock-image:v1", init=False)
    official_logo: bool = field(default=False, init=False)


class _StockImageMixin:
    """Provide an adapter-bound original illustration."""

    _symbol: str

    def generated_image(self) -> GeneratedStockImage:
        """Return an original symbol illustration, not an official company mark."""
        return generate_stock_image(self._symbol)


def generate_stock_image(symbol: str) -> GeneratedStockImage:
    """Render a deterministic abstract SVG for a canonical ticker symbol."""
    if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
        raise ValueError("invalid stock symbol for generated image")
    digest = hashlib.sha256(symbol.encode("ascii")).digest()
    accent = f"#{digest[0]:02x}{digest[1]:02x}{digest[2]:02x}"
    radius = 18 + digest[3] % 14
    font_size = min(12, 112 // len(symbol))
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" '
        'viewBox="0 0 128 128" role="img">'
        f"<title>Generated illustration for {symbol}</title>"
        '<rect width="128" height="128" rx="24" fill="#111827"/>'
        f'<circle cx="64" cy="49" r="{radius}" fill="{accent}"/>'
        '<path d="M23 84h82" stroke="#fff" stroke-width="2"/>'
        f'<text x="64" y="106" text-anchor="middle" fill="#fff" '
        f'font-family="sans-serif" font-size="{font_size}">{symbol}</text></svg>'
    ).encode()
    return GeneratedStockImage(symbol, svg, hashlib.sha256(svg).hexdigest())
