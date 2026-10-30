"""Linear text extraction for the legacy web-fetch adapter."""

import re

_TITLE_START = re.compile(r"<title", re.IGNORECASE)
_TITLE_END = re.compile(r"</title>", re.IGNORECASE)


def _strip_tags(html: str) -> str:
    """Replace each nonempty angle-bracket span with one space."""
    parts: list[str] = []
    start = 0
    while True:
        left = html.find("<", start)
        if left < 0:
            break
        right = html.find(">", left + 1)
        if right < 0:
            break
        if right == left + 1:
            parts.append(html[start : right + 1])
        else:
            parts.extend((html[start:left], " "))
        start = right + 1
    parts.append(html[start:])
    return "".join(parts)


def _title_from_html(html: str) -> str:
    """Return the first complete title with the previous matching semantics."""
    start = _TITLE_START.search(html)
    if start is None:
        return ""
    opening_end = html.find(">", start.end())
    if opening_end < 0:
        return ""
    closing = _TITLE_END.search(html, opening_end + 1)
    if closing is None:
        return ""
    return html[opening_end + 1 : closing.start()].strip()
