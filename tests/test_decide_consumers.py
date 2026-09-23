"""EH-041/042/043: the SDK's own ``Decide`` call sites are evaluate-only and
never authorize; both paths (no runner installed, EG abstains) fall back
deterministically.

EH-041 (connector inbound event triage) has no SDK-owned call site -- see
``agent_connector_sdk/decide/__init__.py``'s module docstring -- so it has no
tests here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest

from agent_connector_sdk import decide
from agent_connector_sdk.decide import Choice, DecisionRunner, Option
from agent_connector_sdk.decide.consumers import (
    NO_WRITE,
    connector_tool,
    propose_writeback,
)
from agent_connector_sdk.decide.options import (
    Q32_ONE,
    declared_source,
    q32,
    text_param,
    unique_sorted,
)
from agent_connector_sdk.ports.decide_runner import Fallback


@dataclass
class FakeRunner:
    """Answers every ``choose``/``achoose`` with a scripted :class:`Choice`.

    ``answer`` is either a fixed :class:`Choice` or a callable from the
    fallback's own answer to one -- so a scripted "EG abstains" reply can
    still return the correct fallback value without the test hardcoding it.
    """

    answer: Choice | Callable[[Fallback], Choice]
    calls: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

    def _reply(
        self, question_id: str, options: Sequence[Option], fallback: Fallback
    ) -> Choice:
        self.calls.append((question_id, tuple(o.option_id for o in options)))
        if isinstance(self.answer, Choice):
            return self.answer
        return self.answer(fallback)

    def choose(
        self,
        question_id: str,
        options: Sequence[Option],
        fallback: Fallback,
        *,
        params: Iterable[Mapping[str, Any]] = (),
        candidates: Mapping[str, Any] | None = None,
    ) -> Choice:
        return self._reply(question_id, options, fallback)

    async def achoose(
        self,
        question_id: str,
        options: Sequence[Option],
        fallback: Fallback,
        *,
        params: Iterable[Mapping[str, Any]] = (),
        candidates: Mapping[str, Any] | None = None,
    ) -> Choice:
        return self._reply(question_id, options, fallback)


def _acted(option_id: str) -> Choice:
    return Choice(option_id, True, "acted")


def _abstained(fallback: Fallback) -> Choice:
    """A runner that abstains still resolves to a concrete fallback answer."""
    return Choice(fallback(), False, "abstained: insufficient_confidence")


@pytest.fixture
def eg() -> Iterator[FakeRunner]:
    """One installed :class:`FakeRunner` per test, scoped and cleaned up."""
    runner = FakeRunner(answer=_acted("unset"))
    token = decide.use_runner(runner)
    yield runner
    decide._RUNNER.reset(token)


def test_no_runner_installed_is_exactly_the_fallback() -> None:
    assert decide.current_runner() is None
    choice = decide.choose("au.connector.tool", [Option("a")], lambda: "a")
    assert choice == Choice("a", False, "no_runner")


async def test_no_runner_installed_is_exactly_the_fallback_async() -> None:
    assert decide.current_runner() is None
    choice = await decide.achoose("au.connector.tool", [Option("a")], lambda: "a")
    assert choice == Choice("a", False, "no_runner")


def test_connector_tool_with_no_runner_returns_the_connector_s_pick() -> None:
    assert decide.current_runner() is None
    assert connector_tool("jira", ["search", "get"], "get") == "get"


def test_connector_tool_never_consults_decide_for_an_unlisted_pick(
    eg: FakeRunner,
) -> None:
    """A pick outside ``tools`` is a caller bug, not a decision -- no EG call."""
    assert connector_tool("jira", ["search", "get"], "missing") == "missing"
    assert eg.calls == []


def test_connector_tool_honors_an_executed_offered_option(eg: FakeRunner) -> None:
    eg.answer = _acted("search")
    assert connector_tool("jira", ["search", "get"], "get") == "search"
    assert eg.calls == [("au.connector.tool", ("get", "search"))]


def test_connector_tool_falls_back_when_decide_abstains(eg: FakeRunner) -> None:
    eg.answer = _abstained
    assert connector_tool("jira", ["search", "get"], "get") == "get"


def test_writeback_with_no_runner_defaults_to_no_write() -> None:
    assert decide.current_runner() is None
    proposals = {"close-incident": {"server": "servicenow-mcp", "tool": "t"}}
    assert propose_writeback(proposals) == (NO_WRITE, None)


def test_writeback_is_only_ever_a_proposal(eg: FakeRunner) -> None:
    proposals = {"close-incident": {"server": "servicenow-mcp", "tool": "t"}}
    eg.answer = _acted("close-incident")
    assert propose_writeback(proposals) == (
        "close-incident",
        proposals["close-incident"],
    )


def test_writeback_falls_back_to_no_write_when_decide_abstains(eg: FakeRunner) -> None:
    proposals = {"close-incident": {"server": "servicenow-mcp", "tool": "t"}}
    eg.answer = _abstained
    assert propose_writeback(proposals) == (NO_WRITE, None)


def test_writeback_custom_default_is_the_fallback(eg: FakeRunner) -> None:
    proposals = {"close-incident": {"a": 1}, "escalate": {"b": 2}}
    eg.answer = _abstained
    assert propose_writeback(proposals, default="escalate") == (
        "escalate",
        proposals["escalate"],
    )


def test_install_runner_is_process_wide_and_use_runner_is_context_scoped() -> None:
    process_runner = FakeRunner(answer=_acted("process"))
    decide.install_runner(process_runner)
    try:
        assert decide.current_runner() is process_runner
        scoped_runner = FakeRunner(answer=_acted("scoped"))
        token = decide.use_runner(scoped_runner)
        try:
            assert decide.current_runner() is scoped_runner
        finally:
            decide._RUNNER.reset(token)
        assert decide.current_runner() is process_runner
    finally:
        decide.install_runner(None)
    assert decide.current_runner() is None


def test_decision_runner_protocol_matches_a_plain_implementation() -> None:
    runner: DecisionRunner = FakeRunner(answer=_acted("x"))
    assert isinstance(runner, DecisionRunner)


def test_options_wire_shape_q32_scaling_and_declared_source() -> None:
    option = Option("search", numbers={"heuristic": 1.0}, texts={"note": "n"})
    wired = option.wire()
    assert wired["option_id"] == "search"
    assert wired["numbers"] == [{"key": "heuristic", "q32": q32(1.0)}]
    assert wired["texts"] == [{"key": "note", "text": "n"}]
    assert q32(1.0) == Q32_ONE
    assert q32(-1.0) == -Q32_ONE

    duplicate = Option("search", numbers={"heuristic": 0.0})
    ordered = unique_sorted([option, Option("get"), duplicate])
    assert [o.option_id for o in ordered] == ["get", "search"]
    assert ordered[1] is option, "first declaration of a repeated id wins"

    source = declared_source([Option("b"), Option("a")])
    assert source == {
        "source": "declared",
        "options": [Option("a").wire(), Option("b").wire()],
    }


def test_text_param_is_never_substituted_into_query_text() -> None:
    assert text_param("connector", "jira") == {
        "name": "connector",
        "value": {"type": "text", "value": "jira"},
    }
