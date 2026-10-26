"""Scope ``owl:imports`` in captured ontologies to the pack that ships them.

epistemic-graph accepts an ``owl:imports`` only when it names an ontology
entry of the same ConnectorPack. Fleet ontologies import shared hub
ontologies, such as ``http://knuckles.team/kg``. The tenant schema composes
every attached pack, so those imports are redundant at pack scope. The pack
builder removes each external import from the ontology body. It records the
external IRI as an ``ontology-import:<iri>`` entry in the ontology entry's
``requires_capabilities`` annotation. A body without external imports stays
byte-identical, so content digests stay deterministic.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection

from epistemic_graph.generated.connector_pack import PackAnnotations

from agent_connector_sdk._turtle import AccessContractError, parse_graph
from agent_connector_sdk.contracts import CapturedArtifact

__all__ = ["IMPORT_REQUIREMENT_PREFIX", "scope_ontology_imports"]

IMPORT_REQUIREMENT_PREFIX = "ontology-import:"

_OWL_IMPORTS_IRI = "http://www.w3.org/2002/07/owl#imports"
_PREDICATE = rf"(?:owl:imports|<{re.escape(_OWL_IMPORTS_IRI)}>)"
_OBJECTS = r"<[^<>\s]*>(?:\s*,\s*<[^<>\s]*>)*"
# One predicate-object list, with the `;` that separates it from a sibling.
_TURTLE_FOLLOWED = re.compile(rf"{_PREDICATE}\s+(?P<objs>{_OBJECTS})\s*;\s*")
# Start at the separating semicolon, consuming only horizontal whitespace
# before it.  A leading ``\s*`` would be able to cross a masked quoted literal
# (whose bytes are deliberately whitespace in the lexer view) and erase part
# of the original literal during surgery.
_TURTLE_PRECEDED = re.compile(rf"[ \t]*;[ \t\r\n]*{_PREDICATE}\s+(?P<objs>{_OBJECTS})")
_TURTLE_ANY = re.compile(rf"{_PREDICATE}\s+(?P<objs>{_OBJECTS})")
_IRI = re.compile(r"<([^<>\s]*)>")
_RDFXML = re.compile(
    r"\s*<owl:imports\s+rdf:resource=\"(?P<iri>[^\"]*)\"\s*/>",
)


def _mask_turtle(text: str) -> str:
    """Mask comments and quoted literals while preserving every character offset.

    Import matching is deliberately done against this lexed view.  A plain
    regular expression over the served bytes can mistake documentation in a
    comment or literal for an RDF predicate/object pair.  IRIs remain visible,
    including ``#`` fragments, because they are RDF terms rather than comments.
    """
    masked = list(text)
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "#":
            index += 1
            while index < length and text[index] != "\n":
                masked[index] = " "
                index += 1
            continue
        if char == "<":
            index += 1
            while index < length:
                if text[index] == ">":
                    index += 1
                    break
                index += 1
            continue

        delimiter: str | None = None
        if text.startswith('"""', index) or text.startswith("'''", index):
            delimiter = text[index : index + 3]
        elif char in {'"', "'"}:
            delimiter = char
        if delimiter is None:
            index += 1
            continue

        for offset in range(len(delimiter)):
            if text[index + offset] != "\n":
                masked[index + offset] = "\x00"
        index += len(delimiter)
        while index < length:
            if text.startswith(delimiter, index):
                for offset in range(len(delimiter)):
                    if text[index + offset] != "\n":
                        masked[index + offset] = "\x00"
                index += len(delimiter)
                break
            if text[index] == "\\" and index + 1 < length:
                masked[index] = "\x00"
                if text[index + 1] != "\n":
                    masked[index + 1] = "\x00"
                index += 2
                continue
            if text[index] != "\n":
                masked[index] = "\x00"
            index += 1
    return "".join(masked)


def _parsed_imports(text: str) -> frozenset[str] | None:
    """Return parsed ``owl:imports`` IRIs, or ``None`` outside flat Turtle.

    The SDK's existing flat Turtle parser gives simple documents semantic
    prefix expansion and comment/string handling.  Rich ontologies (for
    example, those with triple-quoted literals) use the lexer above as a
    position-preserving fallback; they must never fall back to raw-text regex
    matching.
    """
    try:
        graph = parse_graph(text)
    except AccessContractError:
        return None
    return frozenset(
        value
        for properties in graph.values()
        for value in properties.get(_OWL_IMPORTS_IRI, ())
        if isinstance(value, str)
    )


def _masked_sub(
    text: str,
    pattern: re.Pattern[str],
    replace: Callable[[re.Match[str], str], str],
) -> str:
    """Apply substitutions found in the lexed view to the original text."""
    masked = _mask_turtle(text)
    matches = tuple(pattern.finditer(masked))
    if not matches:
        return text
    chunks: list[str] = []
    cursor = 0
    for match in matches:
        start, end = match.span()
        chunks.append(text[cursor:start])
        chunks.append(replace(match, text))
        cursor = end
    chunks.append(text[cursor:])
    return "".join(chunks)


def _keep_iri_text(raw: str, keep: Callable[[str], bool]) -> tuple[str, list[str]]:
    """Keep angle-IRI objects, retaining surrounding whitespace and formatting."""
    matches = tuple(_IRI.finditer(raw))
    kept = [match for match in matches if keep(match.group(1))]
    dropped = [match.group(1) for match in matches if not keep(match.group(1))]
    if not kept:
        return "", dropped
    if len(kept) == len(matches):
        return raw, dropped
    prefix = raw[: matches[0].start()]
    suffix = raw[matches[-1].end() :]
    objects = ", ".join(match.group(0) for match in kept)
    return f"{prefix}{objects}{suffix}", dropped


def _match_is_parsed_import(
    match: re.Match[str], parsed: frozenset[str] | None
) -> bool:
    """Reject a masked match absent from the parser's actual import triples."""
    if parsed is None:
        return True
    return set(_IRI.findall(match.group("objs"))).issubset(parsed)


def _rewrite_turtle(text: str, keep: Callable[[str], bool], dropped: list[str]) -> str:
    parsed = _parsed_imports(text)

    def replace(match: re.Match[str], original: str) -> str:
        if not _match_is_parsed_import(match, parsed):
            return original[match.start() : match.end()]
        start, end = match.span("objs")
        objects, removed = _keep_iri_text(original[start:end], keep)
        if not removed:
            return original[match.start() : match.end()]
        dropped.extend(removed)
        if not objects:
            return ""
        whole = original[match.start() : match.end()]
        offset = match.start()
        return whole[: start - offset] + objects + whole[end - offset :]

    for pattern in (_TURTLE_FOLLOWED, _TURTLE_PRECEDED):
        text = _masked_sub(text, pattern, replace)
    return text


def _rewrite_rdfxml(text: str, keep: Callable[[str], bool], dropped: list[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        iri = match.group("iri")
        if keep(iri):
            return match.group(0)
        dropped.append(iri)
        return ""

    return _RDFXML.sub(replace, text)


def _with_requirements(
    annotations: PackAnnotations, iris: list[str]
) -> PackAnnotations:
    requirements = list(annotations.requires_capabilities or ())
    for iri in sorted(set(iris)):
        token = f"{IMPORT_REQUIREMENT_PREFIX}{iri}"
        if token not in requirements:
            requirements.append(token)
    return annotations.model_copy(update={"requires_capabilities": requirements})


def scope_ontology_imports(
    entry: CapturedArtifact, pack_ontology_uris: Collection[str]
) -> CapturedArtifact:
    """Remove imports outside the pack and record them as requirements.

    Args:
        entry: one captured ``ontology://`` resource.
        pack_ontology_uris: every ontology entry URI in the same pack.

    Returns:
        The entry unchanged when every import names another pack ontology.
        Otherwise a copy with a scoped body and import requirements.
    """

    def keep(iri: str) -> bool:
        return iri != entry.uri and iri in pack_ontology_uris

    dropped: list[str] = []
    if "xml" in entry.media_type:
        body = _rewrite_rdfxml(entry.body, keep, dropped)
    else:
        body = _rewrite_turtle(entry.body, keep, dropped)
    if _TURTLE_ANY.search(_mask_turtle(body)) and "xml" not in entry.media_type:
        # A lone `<s> owl:imports <x> .` statement has no sibling predicate.
        body = _drop_lone_statements(body, keep, dropped)
    if not dropped:
        return entry
    annotations = _with_requirements(entry.annotations, dropped)
    return entry.model_copy(update={"body": body, "annotations": annotations})


_LONE = re.compile(
    rf"^[ \t]*(?:<[^<>\s]*>|[A-Za-z0-9_.-]*:[A-Za-z0-9_.-]*)\s+{_PREDICATE}\s+"
    rf"(?P<objs>{_OBJECTS})\s*\.[ \t]*\n?",
    re.MULTILINE,
)


def _drop_lone_statements(
    text: str, keep: Callable[[str], bool], dropped: list[str]
) -> str:
    parsed = _parsed_imports(text)

    def replace(match: re.Match[str], original: str) -> str:
        if not _match_is_parsed_import(match, parsed):
            return original[match.start() : match.end()]
        start, end = match.span("objs")
        objects, removed = _keep_iri_text(original[start:end], keep)
        if not removed:
            return original[match.start() : match.end()]
        dropped.extend(removed)
        if not objects:
            return ""
        whole = original[match.start() : match.end()]
        offset = match.start()
        return whole[: start - offset] + objects + whole[end - offset :]

    return _masked_sub(text, _LONE, replace)
