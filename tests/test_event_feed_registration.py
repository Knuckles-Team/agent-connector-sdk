"""Certified entry points for the SDK's event-feed bindings."""

import pytest

from scion_sdk.adapters.event_feed import EventFeedSourceAdapter
from scion_sdk.discovery import (
    SOURCE_ADAPTER_GROUP,
    CertifiedExtensions,
    ExtensionActivationError,
    discover_extensions,
    load_extension,
    sdk_reference_extensions,
)
from scion_sdk.manifest.presets import ToolPreset


@pytest.mark.spec("SCION-OBSERVABILITY-FEEDS-R001.5")
def test_event_feed_entrypoints_require_certified_identity() -> None:
    names = ("rum", "security_audit", "ci_cd")
    identities = {item.name: item for item in discover_extensions(SOURCE_ADAPTER_GROUP)}
    assert all(name in identities for name in names)
    preset = ToolPreset(
        name="events", server="feed", tool="events", records_path="events"
    )
    for name in names:
        identity = identities[name]
        assert identity.distribution == "scion-sdk"
        with pytest.raises(ExtensionActivationError):
            load_extension(SOURCE_ADAPTER_GROUP, name, policy=CertifiedExtensions(()))
        wrong_version = CertifiedExtensions(
            (
                (
                    SOURCE_ADAPTER_GROUP,
                    name,
                    identity.distribution,
                    identity.version + "-other",
                ),
            )
        )
        with pytest.raises(ExtensionActivationError):
            load_extension(SOURCE_ADAPTER_GROUP, name, policy=wrong_version)
        factory = load_extension(
            SOURCE_ADAPTER_GROUP, name, policy=sdk_reference_extensions()
        )
        adapter = factory(
            preset,
            connector="feed",
            tool_schema_sha256="a" * 64,
            mapping_reference="connector:feed#mappings/Event",
        )
        assert isinstance(adapter, EventFeedSourceAdapter)
        assert adapter.kind == f"event_feed:{name}"
