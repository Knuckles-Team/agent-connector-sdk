"""Flat Turtle reader for connector access contracts.

The reader accepts ``@prefix`` lines, prefixed names, ``<IRIs>``, ``a``,
string and integer literals, and ``;`` ``,`` ``.``. Blank nodes and
collections are refused.
"""

from __future__ import annotations

import re
from collections import defaultdict

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

_TOKEN_RE = re.compile(
    r"(?P<ws>\s+|#[^\n]*)"
    r"|(?P<iri><[^<>\s]*>)"
    r'|(?P<str>"(?:[^"\\\n]|\\.)*")'
    r"|(?P<int>-?\d+)"
    r"|(?P<prefix>@prefix)"
    r"|(?P<pname>[A-Za-z_]?[\w-]*:(?:[\w-](?:[\w.-]*[\w-])?)?)"
    r"|(?P<a>a(?=\s))"
    r"|(?P<punct>[;,.])"
)

Term = str | int
Triple = tuple[str, str, Term]


class AccessContractError(ValueError):
    """A connector ontology declares an invalid access contract."""


def _tokens(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN_RE.match(text, pos)
        if match is None or match.end() == pos:
            raise AccessContractError(f"unsupported Turtle at offset {pos}")
        kind = match.lastgroup or ""
        if kind != "ws":
            out.append((kind, match.group()))
        pos = match.end()
    return out


class _Reader:
    def __init__(self, text: str) -> None:
        self.toks = _tokens(text)
        self.pos = 0
        self.prefixes: dict[str, str] = {}
        self.triples: list[Triple] = []

    def next(self) -> tuple[str, str]:
        if self.pos >= len(self.toks):
            raise AccessContractError("unexpected end of Turtle")
        self.pos += 1
        return self.toks[self.pos - 1]

    def expect(self, value: str) -> None:
        if self.next()[1] != value:
            raise AccessContractError(f"expected {value!r}")

    def term(self) -> Term:
        kind, value = self.next()
        if kind == "iri":
            return value[1:-1]
        if kind == "a":
            return RDF_TYPE
        if kind == "pname":
            prefix, _, local = value.partition(":")
            if prefix not in self.prefixes:
                raise AccessContractError(f"undeclared prefix {prefix!r}")
            return self.prefixes[prefix] + local
        if kind == "str":
            return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        if kind == "int":
            return int(value)
        raise AccessContractError(f"unexpected token {value!r}")

    def prefix(self) -> None:
        kind, name = self.next()
        iri = self.next()
        if kind != "pname" or not name.endswith(":") or iri[0] != "iri":
            raise AccessContractError("malformed @prefix")
        self.prefixes[name[:-1]] = iri[1][1:-1]
        self.expect(".")

    def statement(self) -> None:
        subject = str(self.term())
        sep = ";"
        while sep == ";":
            predicate = str(self.term())
            sep = ","
            while sep == ",":
                self.triples.append((subject, predicate, self.term()))
                sep = self.next()[1]
        if sep != ".":
            raise AccessContractError("statement must end with '.'")

    def read(self) -> list[Triple]:
        while self.pos < len(self.toks):
            if self.toks[self.pos][0] == "prefix":
                self.pos += 1
                self.prefix()
            else:
                self.statement()
        return self.triples


def parse_graph(text: str) -> dict[str, dict[str, list[Term]]]:
    """Read flat Turtle into a subject -> predicate -> objects index."""
    graph: dict[str, dict[str, list[Term]]] = defaultdict(lambda: defaultdict(list))
    for subject, predicate, obj in _Reader(text).read():
        graph[subject][predicate].append(obj)
    return graph
