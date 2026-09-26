"""Generic stream transport decoding is shared by connector consumers."""

import pytest

from agent_connector_sdk.transports.stream_payload import (
    decode_json_object_or_none,
    decode_json_value_or_none,
    decode_stream_payload,
)


def test_decodes_utf8_json_object():
    assert decode_stream_payload(b'{"event_id":"e1","payload":{"x":1}}') == {
        "event_id": "e1",
        "payload": {"x": 1},
    }


def test_plain_text_and_invalid_utf8_preserve_raw_fallback():
    assert decode_stream_payload(b"not json") == {"raw": "not json"}
    assert decode_stream_payload(b"\xff") == {"raw": "b'\\xff'"}


def test_dict_passes_through_and_other_values_are_stringified():
    row = {"event_id": "e2"}
    assert decode_stream_payload(row) is row
    assert decode_stream_payload(3) == {"raw": "3"}


@pytest.mark.parametrize("payload", ["[]", "null", "42", '"text"'])
def test_non_object_json_fails_before_consumer_reads_fields(payload):
    with pytest.raises(ValueError, match="must be an object"):
        decode_stream_payload(payload)


@pytest.mark.parametrize("value", [b"not-json", b"\xff", "[]", "null", None, 2])
def test_strict_json_object_decoder_counts_malformed_input(value):
    assert decode_json_object_or_none(value) is None


def test_strict_json_object_decoder_accepts_wire_or_decoded_object():
    row = {"run": {"runId": "r1"}}
    assert decode_json_object_or_none(row) is row
    assert decode_json_object_or_none(b'{"run":{"runId":"r1"}}') == row


def test_json_value_decoder_preserves_debezium_scalar_keys():
    assert decode_json_value_or_none(b'"key-1"') == "key-1"
    assert decode_json_value_or_none(b"42") == 42
    assert decode_json_value_or_none(b'{"id":1}') == {"id": 1}
    assert decode_json_value_or_none(b"not-json") is None
    assert decode_json_value_or_none(b"\xff") is None
