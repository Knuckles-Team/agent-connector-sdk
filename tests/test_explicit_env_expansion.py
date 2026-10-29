"""Explicit, non-ambient value expansion."""

import pytest

from agent_connector_sdk.utilities import expand_env_vars, to_integer


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R780.12")
def test_expand_uses_only_explicit_values_and_defaults(monkeypatch):
    monkeypatch.setenv("PORT", "9999")
    assert (
        expand_env_vars(
            "${PORT:-80}/${MISSING}/${EMPTY:-fallback}",
            values={"PORT": "42", "EMPTY": ""},
        )
        == "42//fallback"
    )
    assert expand_env_vars("${PORT:-80}", values={}) == "80"
    assert to_integer("${PORT}") == 0


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R780.12")
def test_expansion_is_single_pass_and_refuses_non_string_values():
    assert expand_env_vars("${A}", values={"A": "${B}", "B": "42"}) == "${B}"
    with pytest.raises(ValueError, match="values must be strings"):
        expand_env_vars("${A}", values={"A": 42})
