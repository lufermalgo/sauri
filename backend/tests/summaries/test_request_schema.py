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
