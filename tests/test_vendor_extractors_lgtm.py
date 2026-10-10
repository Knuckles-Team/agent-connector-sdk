"""SDK-SOURCE-INGEST-R006.8: the LGTM vendor extractor port."""

from __future__ import annotations

import pytest

from agent_connector_sdk.ingest import ChangeSet, Entity
from agent_connector_sdk.vendor_extractors import (
    get_vendor_extractor,
    list_vendor_extractors,
)
from agent_connector_sdk.vendor_extractors.lgtm import CATEGORY, extract


class _FakeClient:
    def __init__(self, dashboards: object, alerts: object, datasources: object) -> None:
        self._dashboards = dashboards
        self._alerts = alerts
        self._datasources = datasources

    def get_dashboards(self) -> object:
        return self._dashboards

    def get_alerts(self) -> object:
        return self._alerts

    def list_datasources(self) -> object:
        return self._datasources


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.8")
def test_extract_returns_dashboard_alert_and_datasource_entities() -> None:
    config = {
        "client": _FakeClient(
            dashboards=[{"uid": "d1", "title": "Fleet"}],
            alerts=[{"fingerprint": "f1", "labels": {"alertname": "HighCPU"}}],
            datasources=[{"uid": "ds1", "name": "Prometheus", "type": "prometheus"}],
        )
    }

    result = extract(config)

    assert isinstance(result, ChangeSet)
    assert len(result.entities) == 3
    dashboard, alert, datasource = result.entities
    assert isinstance(dashboard, Entity)
    assert dashboard.id == "lgtm_dash:d1"
    assert dashboard.node_type == "Dashboard"
    assert alert.id == "lgtm_alert:f1"
    assert alert.node_type == "Alert"
    assert alert.properties["name"] == "HighCPU"
    assert datasource.id == "lgtm_ds:ds1"
    assert datasource.node_type == "DataSource"
    assert result.relationships == ()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.8")
def test_extract_unwraps_a_dict_shaped_response() -> None:
    config = {
        "client": _FakeClient(
            dashboards={"data": [{"uid": "d1", "title": "Fleet"}]},
            alerts=[],
            datasources=[],
        )
    }

    result = extract(config)

    assert [entity.id for entity in result.entities] == ["lgtm_dash:d1"]


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.8")
def test_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert extract({}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.8")
def test_extract_returns_an_empty_change_set_when_get_dashboards_raises() -> None:
    class _BrokenClient:
        def get_dashboards(self) -> object:
            raise RuntimeError("down")

        def get_alerts(self) -> object:
            return []

        def list_datasources(self) -> object:
            return []

    assert extract({"client": _BrokenClient()}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.8")
def test_lgtm_self_registers_under_the_vendor_extractor_registry() -> None:
    registered = get_vendor_extractor(CATEGORY)

    assert registered is not None
    assert registered.extract is extract
    assert CATEGORY in [vendor.category for vendor in list_vendor_extractors()]
