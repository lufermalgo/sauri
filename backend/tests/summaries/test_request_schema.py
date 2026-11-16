"""The schema sent to the provider must be self-contained: local grammars ignore $ref."""

import json

from app.summaries.engine import _request_schema


def _walk(node):
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def test_schema_has_no_references_and_closes_every_object():
    schema = _request_schema(["P0001", "P0002"])
    assert "$ref" not in json.dumps(schema)
    assert "$defs" not in schema
    for node in _walk(schema):
        if isinstance(node, dict) and node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert node["required"] == list(node["properties"])


def test_passage_ids_are_enumerated_in_sources():
    schema = _request_schema(["P0001", "P0002"])
    sources = schema["properties"]["key_points"]["items"]["properties"]["sources"]["items"]
    assert sources["properties"]["passage_id"]["enum"] == ["P0001", "P0002"]


def test_schema_describes_v2_blocks_and_server_stamps_the_version():
    schema = _request_schema(["P0001"])
    assert list(schema["properties"]) == ["topic", "key_points", "conclusion", "review_state"]
    assert schema["required"] == ["topic", "key_points", "conclusion", "review_state"]
    assert schema["properties"]["topic"]["maxLength"] == 1200
    assert schema["properties"]["conclusion"]["maxLength"] == 1200
    block = schema["properties"]["key_points"]["items"]
    assert list(block["properties"]) == ["title", "items", "sources"]
    assert block["properties"]["title"]["maxLength"] == 160
    assert block["properties"]["sources"]["minItems"] == 1 and block["properties"]["sources"]["maxItems"] == 4
    item = block["properties"]["items"]["items"]
    assert list(item["properties"]) == ["text", "sub_items"]
    assert item["properties"]["sub_items"]["items"] == {"type": "string", "minLength": 1, "maxLength": 500}


def test_system_prompt_describes_structure_and_forbids_time_references():
    from app.summaries.engine import SYSTEM_PROMPT

    for required in ("topic paragraph", "thematic block", "sub_items", "conclusion paragraph",
                     "never contain minutes, timestamps", "one to four supplied passage IDs",
                     "goals, proposals, decisions and achievements",
                     "exactly as they appear in the transcript", "never translate, rename or replace a label"):
        assert required in SYSTEM_PROMPT
    assert "Speaker N" not in SYSTEM_PROMPT
