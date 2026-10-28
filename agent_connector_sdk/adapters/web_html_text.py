"""Linear text extraction for the legacy web-fetch adapter."""


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
