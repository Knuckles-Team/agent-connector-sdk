"""SDK-SOURCE-INGEST-R006.6: the Kafka vendor extractor port."""

from __future__ import annotations
import pytest

from agent_connector_sdk.ingest import ChangeSet, Entity
from agent_connector_sdk.vendor_extractors import (
    get_vendor_extractor,
    list_vendor_extractors,
)
from agent_connector_sdk.vendor_extractors.kafka import CATEGORY, extract


class _FakeClient:
    def __init__(self, topics: object, groups: object) -> None:
        self._topics = topics
        self._groups = groups

    def list_topics(self) -> object:
        return self._topics

    def list_consumer_groups(self) -> object:
        return self._groups


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.6")
def test_extract_returns_topic_and_service_entities() -> None:
    config = {
        "client": _FakeClient(
            topics=["orders", "payments"],
            groups=[{"group_id": "billing"}],
        )
    }

    result = extract(config)

    assert isinstance(result, ChangeSet)
    assert len(result.entities) == 3
    topic = result.entities[0]
    assert isinstance(topic, Entity)
    assert topic.id == "kafka_topic:orders"
    assert topic.node_type == "Topic"
    assert topic.properties["domain"] == "kafka"
    group = result.entities[2]
    assert group.id == "kafka_group:billing"
    assert group.node_type == "Service"
    assert group.properties["ci_class"] == "consumer_group"
    assert result.relationships == ()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.6")
def test_extract_unwraps_a_dict_shaped_topics_response() -> None:
    config = {"client": _FakeClient(topics={"data": ["orders"]}, groups=[])}

    result = extract(config)

    assert [entity.id for entity in result.entities] == ["kafka_topic:orders"]


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.6")
def test_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert extract({}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.6")
def test_extract_returns_an_empty_change_set_when_list_topics_raises() -> None:
    class _BrokenClient:
        def list_topics(self) -> object:
            raise RuntimeError("down")

        def list_consumer_groups(self) -> object:
            return []

    assert extract({"client": _BrokenClient()}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.6")
def test_kafka_self_registers_under_the_vendor_extractor_registry() -> None:
    registered = get_vendor_extractor(CATEGORY)

    assert registered is not None
    assert registered.extract is extract
    assert CATEGORY in [vendor.category for vendor in list_vendor_extractors()]
