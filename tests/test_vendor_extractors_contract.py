"""The typed vendor-extractor contract itself (SDK-SOURCE-INGEST-R006.1).

Covers the symbols ``tests/test_vendor_extractors_uptime_kuma.py`` exercises
only indirectly: the ``VendorExtractor``/``VendorExtractFn`` types, explicit
``register_vendor_extractor``, and ``discover_vendor_extractors`` (which
imports every vendor module under the package so each self-registers).
"""

from __future__ import annotations
import pytest

from agent_connector_sdk.ingest import ChangeSet
from agent_connector_sdk.vendor_extractors import (
    VendorExtractFn,
    VendorExtractor,
    discover_vendor_extractors,
    get_vendor_extractor,
    list_vendor_extractors,
    register_vendor_extractor,
)

_CATEGORY = "test_only_vendor"


def _fn(config: object) -> ChangeSet:
    return ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.1")
def test_vendor_extractor_is_a_plain_category_extract_description_record() -> None:
    fn: VendorExtractFn = _fn
    vendor = VendorExtractor(category=_CATEGORY, extract=fn, description="test vendor")

    assert vendor.category == _CATEGORY
    assert vendor.extract is fn
    assert vendor.description == "test vendor"


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.1")
def test_register_vendor_extractor_makes_it_discoverable_by_category() -> None:
    register_vendor_extractor(_CATEGORY, _fn, description="test vendor")

    registered = get_vendor_extractor(_CATEGORY)

    assert registered is not None
    assert registered.extract is _fn
    assert _CATEGORY in [vendor.category for vendor in list_vendor_extractors()]


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.1")
def test_discover_vendor_extractors_imports_every_module_and_self_registers() -> None:
    discover_vendor_extractors()

    categories = {vendor.category for vendor in list_vendor_extractors()}

    assert "uptime_kuma" in categories
    assert "ansible" in categories
