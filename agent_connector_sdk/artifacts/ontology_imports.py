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
from itertools import pairwise

from epistemic_graph.generated.connector_pack import PackAnnotations

from agent_connector_sdk._turtle import AccessContractError, parse_graph
from agent_connector_sdk.contracts import CapturedArtifact

__all__ = ["IMPORT_REQUIREMENT_PREFIX", "scope_ontology_imports"]

IMPORT_REQUIREMENT_PREFIX = "ontology-import:"

_OWL_IMPORTS_IRI = "http://www.w3.org/2002/07/owl#imports"
_PREDICATE = rf"(?:owl:imports|<{re.escape(_OWL_IMPORTS_IRI)}>)"
_PREDICATE_RE = re.compile(_PREDICATE)
_COMMA_RE = re.compile(",")
_SUBJECT_RE = re.compile(r"(?:<[^<>\s]*>|[A-Za-z0-9_.-]*:[A-Za-z0-9_.-]*)")
_OBJECTS = r"<[^<>\s]*>(?:\s*,\s*<[^<>\s]*>)*"
_TURTLE_GAP = r"(?:[ \t\r\n]+|#[^\n]*(?:\n|$))*"
_TURTLE_OBJECT = r"<[^<>\s]*>"
_TURTLE_OBJECTS = rf"{_TURTLE_OBJECT}(?:{_TURTLE_GAP},{_TURTLE_GAP}{_TURTLE_OBJECT})*"
# One predicate-object list, with the `;` that separates it from a sibling.
_TURTLE_FOLLOWED = re.compile(rf"{_PREDICATE}\s+(?P<objs>{_OBJECTS})\s*;\s*")
# Start at the separating semicolon, consuming only horizontal whitespace
# before it.  A leading ``\s*`` would be able to cross a masked quoted literal
# (whose bytes are deliberately whitespace in the lexer view) and erase part
# of the original literal during surgery.
_TURTLE_PRECEDED = re.compile(rf"[ \t]*;[ \t\r\n]*{_PREDICATE}\s+(?P<objs>{_OBJECTS})")
_TURTLE_ANY = re.compile(rf"{_PREDICATE}{_TURTLE_GAP}(?P<objs>{_TURTLE_OBJECTS})")
# A final import property can be separated from its sibling by a comment.
# ``#`` remains visible in the masked view, so this gap can skip comments
# without allowing a replacement to treat their original bytes as tokens.
_TURTLE_FINAL = re.compile(
    rf";{_TURTLE_GAP}{_PREDICATE}{_TURTLE_GAP}"
    rf"(?P<objs>{_TURTLE_OBJECTS}){_TURTLE_GAP}\."
)
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


def _match_is_parsed_import(
    match: re.Match[str], parsed: frozenset[str] | None
) -> bool:
    """Reject a masked match absent from the parser's actual import triples."""
    if parsed is None:
        return True
    return set(_IRI.findall(match.group("objs"))).issubset(parsed)


def _apply_edits(
    text: str,
    match: re.Match[str],
    edits: Collection[tuple[int, int, str]],
) -> str:
    """Apply token-span edits while retaining every unedited source byte."""
    start, end = match.span()
    chunks: list[str] = []
    cursor = start
    for edit_start, edit_end, replacement in sorted(edits):
        if edit_start < start or edit_end > end or edit_start < cursor:
            raise ValueError("overlapping or out-of-range Turtle token edit")
        chunks.append(text[cursor:edit_start])
        chunks.append(replacement)
        cursor = edit_end
    chunks.append(text[cursor:end])
    return "".join(chunks)


def _import_object_spans(
    original: str, match: re.Match[str]
) -> tuple[re.Match[str], tuple[re.Match[str], ...]] | None:
    """Locate actual predicate/object tokens in a masked match.

    The regex match may contain comments between tokens.  Looking up spans in
    the masked view keeps comment examples and literal contents out of the
    object list while retaining their original offsets for surgical edits.
    """
    masked = _mask_turtle(original)
    predicate = _PREDICATE_RE.search(masked, match.start(), match.end())
    if predicate is None:
        return None
    object_start, object_end = match.span("objs")
    objects = tuple(_IRI.finditer(masked, object_start, object_end))
    if not objects:
        return None
    return predicate, objects


def _punctuation_span(
    masked: str, punctuation: str, start: int, end: int, *, reverse: bool = False
) -> tuple[int, int] | None:
    """Find punctuation visible in the masked lexical view."""
    if reverse:
        position = masked.rfind(punctuation, start, end)
    else:
        position = masked.find(punctuation, start, end)
    if position < 0:
        return None
    return position, position + len(punctuation)


def _plain_gap_edit(text: str, start: int, end: int) -> tuple[int, int, str] | None:
    """Drop a token gap only when it contains no comment bytes."""
    if start >= end or "#" in text[start:end]:
        return None
    return start, end, ""


def _rewrite_import_match(
    match: re.Match[str],
    original: str,
    keep: Callable[[str], bool],
    parsed: frozenset[str] | None,
    dropped: list[str],
    *,
    preceding_separator: bool = False,
    following_separator: bool = False,
    remove_subject: bool = False,
    remove_terminator: bool = False,
) -> str:
    """Rewrite only actual import tokens, preserving comments and gaps."""
    if not _match_is_parsed_import(match, parsed):
        return original[match.start() : match.end()]
    located = _import_object_spans(original, match)
    if located is None:
        return original[match.start() : match.end()]
    predicate, objects = located
    decisions = [
        (object_match, keep(object_match.group(1))) for object_match in objects
    ]
    removed = [
        object_match.group(1) for object_match, retained in decisions if not retained
    ]
    if not removed:
        return original[match.start() : match.end()]
    dropped.extend(removed)

    masked = _mask_turtle(original)
    edits: list[tuple[int, int, str]] = []
    retained = [object_match for object_match, keep_object in decisions if keep_object]
    if not retained:
        for object_match in objects:
            edits.append((object_match.start(), object_match.end(), ""))
        for comma_match in _COMMA_RE.finditer(
            masked, objects[0].end(), objects[-1].start()
        ):
            edits.append((comma_match.start(), comma_match.end(), ""))
        edits.append((predicate.start(), predicate.end(), ""))
        if preceding_separator:
            separator = _punctuation_span(
                masked, ";", match.start(), predicate.start(), reverse=True
            )
            if separator is not None:
                edits.append((*separator, ""))
        if following_separator:
            separator = _punctuation_span(masked, ";", objects[-1].end(), match.end())
            if separator is not None:
                edits.append((*separator, ""))
        if remove_subject:
            subject = _SUBJECT_RE.search(masked, match.start(), predicate.start())
            if subject is not None:
                edits.append((subject.start(), subject.end(), ""))
        if remove_terminator:
            terminator = _punctuation_span(masked, ".", objects[-1].end(), match.end())
            if terminator is not None:
                edits.append((*terminator, ""))
        token_spans = sorted(
            (edit_start, edit_end)
            for edit_start, edit_end, _ in edits
            if edit_start < edit_end
        )
        if token_spans:
            end_boundary = match.end()
            if (
                not remove_terminator
                and preceding_separator
                and not following_separator
            ):
                terminator = _punctuation_span(
                    masked, ".", objects[-1].end(), match.end()
                )
                if terminator is not None:
                    end_boundary = terminator[0]
            gaps = [
                _plain_gap_edit(original, match.start(), token_spans[0][0]),
                *(
                    _plain_gap_edit(original, previous[1], current[0])
                    for previous, current in pairwise(token_spans)
                ),
                _plain_gap_edit(original, token_spans[-1][1], end_boundary),
            ]
            edits.extend(gap for gap in gaps if gap is not None)
    else:
        for index, (object_match, keep_object) in enumerate(decisions):
            if keep_object:
                continue
            edits.append((object_match.start(), object_match.end(), ""))
            comma: tuple[int, int] | None
            next_object_start: int
            if index + 1 < len(objects):
                comma = _punctuation_span(
                    masked, ",", object_match.end(), objects[index + 1].start()
                )
                next_object_start = objects[index + 1].start()
            else:
                comma = _punctuation_span(
                    masked,
                    ",",
                    objects[index - 1].end(),
                    object_match.start(),
                    reverse=True,
                )
                next_object_start = object_match.start()
            if comma is not None:
                edits.append((*comma, ""))
                gap = _plain_gap_edit(original, comma[1], next_object_start)
                if gap is not None:
                    edits.append(gap)
    return _apply_edits(original, match, edits)


def _rewrite_turtle(text: str, keep: Callable[[str], bool], dropped: list[str]) -> str:
    parsed = _parsed_imports(text)

    for pattern, preceding_separator, following_separator in (
        (_TURTLE_FOLLOWED, False, True),
        (_TURTLE_PRECEDED, True, False),
        (_TURTLE_FINAL, True, False),
    ):

        def replace(
            match: re.Match[str],
            original: str,
            preceding_separator: bool = preceding_separator,
            following_separator: bool = following_separator,
        ) -> str:
            return _rewrite_import_match(
                match,
                original,
                keep,
                parsed,
                dropped,
                preceding_separator=preceding_separator,
                following_separator=following_separator,
            )

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
    rf"^[ \t]*(?:<[^<>\s]*>|[A-Za-z0-9_.-]*:[A-Za-z0-9_.-]*){_TURTLE_GAP}"
    rf"{_PREDICATE}{_TURTLE_GAP}(?P<objs>{_TURTLE_OBJECTS})"
    rf"{_TURTLE_GAP}\.[ \t]*\n?",
    re.MULTILINE,
)


def _drop_lone_statements(
    text: str, keep: Callable[[str], bool], dropped: list[str]
) -> str:
    parsed = _parsed_imports(text)

    return _masked_sub(
        text,
        _LONE,
        lambda match, original: _rewrite_import_match(
            match,
            original,
            keep,
            parsed,
            dropped,
            remove_subject=True,
            remove_terminator=True,
        ),
    )
