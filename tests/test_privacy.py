"""The persistence privacy guard redacts content and keeps identities."""

from __future__ import annotations

import pytest

from agent_connector_sdk.privacy import (
    PersistencePrivacyGuard,
    PrivacyReport,
    persistence_reference,
    sanitize_for_persistence,
)
from agent_connector_sdk.privacy_rules import (
    PATTERNS,
    STRUCTURAL_ID_FIELDS,
    field_name,
    field_redaction,
    runtime_deny_terms,
    usable_terms,
)


def test_patterns_fields_and_structural_ids() -> None:
    value = {
        "id": "GB82WEST12345698765432",
        "content_hash": "ab12" + "c" * 60,
        "note": "mail a@b.example from 192.168.1.4 at /home/alice/x",
        "password": "hunter2",
        "url": "https://internal.example/x",
        "user": {"name": "Alice"},
        "tags": ("ok", 5, None, True),
        "empty_token": "",
        "blob": object(),
    }
    clean, report = sanitize_for_persistence(value, deny_terms=[])
    assert clean["id"] == value["id"] and clean["content_hash"] == value["content_hash"]
    assert clean["note"] == (
        "mail [REDACTED_EMAIL] from [REDACTED_IPV4] at [REDACTED_POSIX_USER_PATH]"
    )
    assert clean["password"] == "[REDACTED_SECRET]"
    assert clean["url"] == "[REDACTED_LOCATION]"
    assert clean["user"] == {"name": "[REDACTED_PERSON]"}
    assert clean["tags"] == ["ok", 5, None, True]
    assert clean["empty_token"] == ""
    assert clean["blob"] == "[REDACTED_OBJECT:object]"
    assert isinstance(report, PrivacyReport) and report.changed
    assert set(report.as_dict()["detected_types"]) >= {"email", "secret_field"}


def test_deny_terms_are_applied_without_being_reported() -> None:
    guard = PersistencePrivacyGuard(deny_terms=["acme-lab", "x", "admin"])
    text, report = guard.sanitize_text("deployed on ACME-LAB by admin")
    assert text == "deployed on [REDACTED_IDENTITY_TERM] by admin"
    assert report.detected_types == ("identity_term",)
    assert "acme" not in str(report.as_dict())


def test_policy_deny_terms_resolve_from_a_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DENY_TERMS", '["project-zeta"]')
    monkeypatch.setenv("PERSISTENCE_PRIVACY_DENY_TERMS_REF", "env://DENY_TERMS")
    runtime_deny_terms.cache_clear()
    clean, _ = PersistencePrivacyGuard().sanitize_text("project-zeta rollout")
    assert clean == "[REDACTED_IDENTITY_TERM] rollout"
    monkeypatch.setenv("DENY_TERMS", "alpha-one, beta-two")
    runtime_deny_terms.cache_clear()
    assert "[REDACTED" in PersistencePrivacyGuard().sanitize_text("beta-two")[0]
    runtime_deny_terms.cache_clear()


def test_persistence_reference_is_stable_and_opaque() -> None:
    first = persistence_reference("Delegated Actor", "alice@example.com")
    assert first.startswith("pref_delegated_actor_") and "alice" not in first
    assert persistence_reference("delegated actor", "alice@example.com") == first
    assert persistence_reference("x", first) == first
    assert persistence_reference("x", "") == ""
    assert persistence_reference("x", "v", namespace="n") != persistence_reference(
        "x", "v"
    )


def test_redaction_rules_are_table_driven() -> None:
    assert field_name(" Owner-Name ") == "owner_name"
    assert field_redaction("password", "x", ()) == ("secret_field", "[REDACTED_SECRET]")
    assert field_redaction("name", "Alice", ("user",)) == (
        "personal_field",
        "[REDACTED_PERSON]",
    )
    assert field_redaction("password", "", ()) is None
    assert "content_hash" in STRUCTURAL_ID_FIELDS
    assert {label for label, _ in PATTERNS} >= {"email", "ipv4", "iban"}
    assert usable_terms([" ab ", "admin", "acme-lab"]) == ("acme-lab",)
    assert isinstance(runtime_deny_terms(), tuple)
