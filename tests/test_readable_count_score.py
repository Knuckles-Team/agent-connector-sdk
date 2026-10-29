"""Count-based scoring does not infer answers or invent empty-set scores."""

import pytest

from agent_connector_sdk.artifacts import ReadableScore, score_readable_answers


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R048.8")
def test_score_is_derived_from_graded_question_counts() -> None:
    result = score_readable_answers([True, False, True, True])
    assert isinstance(result, ReadableScore)
    assert result.question_count == 4
    assert result.answered_count == 3
    assert result.score == 0.75
    assert score_readable_answers([False]).score == 0.0
    assert score_readable_answers([True]).score == 1.0


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R048.8")
def test_invalid_counts_and_ungraded_answers_refuse() -> None:
    for counts in ((0, 0), (2, -1), (2, 3), (True, 0), (2, False)):
        with pytest.raises(ValueError):
            ReadableScore(*counts)
    for answers in ([], [True, 1], ["true"]):
        with pytest.raises(ValueError):
            score_readable_answers(answers)
