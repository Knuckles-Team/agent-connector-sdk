"""Check that a connector ontology rolls up to the epistemic-graph core namespace.

Every class a connector's ``ontology/*.ttl`` declares must reach a class of the
core namespace through ``rdfs:subClassOf``, directly or through other declared
classes (SDK-CONNECTOR-CONTROL-R073).
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["CORE_NAMESPACE", "orphan_classes", "parse_triples"]

CORE_NAMESPACE = "http://knuckles.team/kg#"
_OWL_CLASS = "http://www.w3.org/2002/07/owl#Class"
_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_SUBCLASS = "http://www.w3.org/2000/01/rdf-schema#subClassOf"

_STRING = re.compile(r'"""(?:.|\n)*?"""|"(?:[^"\\\n]|\\.)*"')
_IRI = re.compile(r"<([^<>\s]*)>")
_PREFIX = re.compile(r"(?im)^\s*@?prefix\s+([A-Za-z][\w.-]*)?:\s+\x00(\d+)\s*\.?")
_END = re.compile(r"\s\.(?=\s|$)|(?<=[\]>)\w\"'])\.(?=\s|$)")


def parse_triples(text: str) -> list[tuple[str, str, str]]:
    """Subject, predicate and object of a Turtle file; names expand, literals drop."""
    iris: list[str] = []

    def keep(match: re.Match[str]) -> str:
        iris.append(match.group(1))
        return f" \x00{len(iris)} "

    body = re.sub(r"(?m)#[^\n]*$", "", _IRI.sub(keep, _STRING.sub(' "" ', text)))
    prefixes = {
        m.group(1) or "": iris[int(m.group(2)) - 1] for m in _PREFIX.finditer(body)
    }
    body = re.sub(r"\[[^\[\]]*\]", " _:b ", _PREFIX.sub("", body))

    def expand(token: str) -> str:
        if token.startswith("\x00"):
            return iris[int(token[1:]) - 1]
        prefix, sep, local = token.partition(":")
        if sep and prefix in prefixes:
            return prefixes[prefix] + local
        return _RDF_TYPE if token == "a" else token

    triples: list[tuple[str, str, str]] = []
    for statement in _END.split(body):
        tokens = statement.replace(";", " ; ").replace(",", " , ").split()
        subject, predicate, fresh = "", "", True
        for index, token in enumerate(tokens):
            if index == 0:
                subject = expand(token)
            elif token == ";":
                fresh = True
            elif token != ",":
                if fresh:
                    predicate, fresh = expand(token), False
                else:
                    triples.append((subject, predicate, expand(token)))
    return triples


def orphan_classes(path: Path) -> set[str]:
    """Classes declared in ``path`` that do not reach the core namespace."""
    triples = parse_triples(path.read_text(encoding="utf-8"))
    declared = {s for s, p, o in triples if p == _RDF_TYPE and o == _OWL_CLASS}
    linked: set[str] = set()
    changed = True
    while changed:
        changed = False
        for cls in declared - linked:
            if cls.startswith(CORE_NAMESPACE):
                continue
            ups = {o for s, p, o in triples if s == cls and p == _SUBCLASS}
            if any(u.startswith(CORE_NAMESPACE) or u in linked for u in ups):
                linked.add(cls)
                changed = True
    return {c for c in declared - linked if not c.startswith(CORE_NAMESPACE)}
