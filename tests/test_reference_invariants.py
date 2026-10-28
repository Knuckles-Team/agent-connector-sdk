"""Secret-reference objects retain the parser's security invariants."""

import pytest

from agent_connector_sdk.credentials.provider import CredentialProvider
from agent_connector_sdk.credentials.references import (
    SecretReference,
    SecretReferenceError,
)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R035.8")
@pytest.mark.parametrize(
    "fields",
    [
        {
            "scheme": "openbao",
            "target": "apps/owner/../other#KEY",
            "mount": "apps",
            "path": "owner/../other",
            "field": "KEY",
        },
        {
            "scheme": "openbao",
            "target": "apps/other#KEY",
            "mount": "apps",
            "path": "owner/resource",
            "field": "KEY",
        },
        {
            "scheme": "openbao",
            "target": "apps/owner#KEY@1",
            "mount": "apps",
            "path": "owner",
            "field": "KEY",
            "version": True,
        },
        {"scheme": "env", "target": "BAD/NAME"},
    ],
)
def test_forged_reference_never_reaches_resolver(fields):
    calls = []

    class Resolver:
        def resolve(self, reference):
            calls.append(reference)
            return "synthetic"

    provider = CredentialProvider(resolver=Resolver(), connector="owner")
    with pytest.raises(SecretReferenceError):
        provider.get_secret(SecretReference(**fields))
    assert calls == []
