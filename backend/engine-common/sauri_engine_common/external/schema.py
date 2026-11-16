"""Adapt a strict JSON Schema to what a provider's structured-output mode accepts.

``adapt_schema_for`` never changes the contract: it returns the adapted schema that is sent to the provider
and the list of constraints it had to drop. The caller keeps the ORIGINAL schema and validates the provider's
answer against it afterwards, so a dropped ``maxItems`` or a made-up citation is still rejected locally.

Anthropic rules (platform.claude.com/docs/en/build-with-claude/structured-outputs, "JSON Schema limitations",
checked 2026-11-16): not supported are recursive schemas, complex types in enums, external ``$ref``,
numerical constraints, ``minLength``/``maxLength``, array constraints beyond ``minItems`` of 0 or 1, and
``additionalProperties`` other than ``false``; ``allOf`` with ``$ref`` is not supported; string ``format`` is
limited to a list; ``pattern`` cannot use backreferences, lookaround or word boundaries. ``maxItems`` and
``uniqueItems`` are not on the supported list, so they are removed too (the official SDKs do the same).
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Final

from sauri_engine_common.external.errors import ProviderError

ANTHROPIC_FORMATS: Final = frozenset(
    {"date-time", "time", "date", "duration", "email", "hostname", "uri", "ipv4", "ipv6", "uuid"}
)
# Keywords the provider rejects (or does not list as supported) and that carry no structure.
_ANTHROPIC_DROPPED: Final = (
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "maxItems",
    "uniqueItems",
    "minContains",
    "maxContains",
    "minProperties",
    "maxProperties",
)
_UNSUPPORTED_REGEX: Final = re.compile(r"\\[1-9bB]|\(\?[=!<]")
_SUBSCHEMA_KEYS: Final = frozenset(
    {"items", "additionalItems", "not", "if", "then", "else", "anyOf", "allOf", "oneOf", "prefixItems"}
)
_MAX_DEPTH: Final = 64
_MAX_NOTE_CHARS: Final = 400


@dataclass(frozen=True)
class Removal:
    """One constraint taken out of the schema sent to the provider."""

    path: str  # JSON pointer style location of the schema node, "" for the root
    keyword: str
    value: Any


@dataclass(frozen=True)
class AdaptedSchema:
    schema: dict[str, Any]
    removed: tuple[Removal, ...]


class SchemaNotAdaptableError(ProviderError):
    """The schema uses a feature the provider cannot take and no removal preserves its meaning."""

    def __init__(self, reason: str) -> None:
        super().__init__("provider_bad_request", reason=reason)


def adapt_schema_for(transport: str, schema: dict[str, Any]) -> AdaptedSchema:
    """The schema to send for ``transport`` plus the record of what was removed.

    ``openai-chat`` providers take the strict schema as is (a provider that cannot is detected by its own
    ``400``); ``anthropic-messages`` gets the adaptation described in the module docstring.
    """
    adapted = copy.deepcopy(schema)
    if transport != "anthropic-messages":
        return AdaptedSchema(adapted, ())
    removed: list[Removal] = []
    _adapt_anthropic(adapted, "", removed, 0)
    _check_refs(adapted)
    return AdaptedSchema(adapted, tuple(removed))


def _record(node: dict[str, Any], path: str, keyword: str, removed: list[Removal]) -> None:
    removed.append(Removal(path, keyword, node.pop(keyword)))


def _describe(node: dict[str, Any], removed_here: list[Removal]) -> None:
    """Say the dropped constraints in the field description so the model still sees them (as the SDKs do)."""
    if not removed_here:
        return
    note = ", ".join(f"{item.keyword}={item.value!r}" for item in removed_here)[:_MAX_NOTE_CHARS]
    existing = node.get("description")
    node["description"] = f"{existing} ({note})" if isinstance(existing, str) and existing else f"({note})"


def _adapt_anthropic(node: Any, path: str, removed: list[Removal], depth: int) -> None:
    if depth > _MAX_DEPTH:
        raise SchemaNotAdaptableError("schema_too_deep")
    if isinstance(node, list):
        for index, item in enumerate(node):
            _adapt_anthropic(item, f"{path}/{index}", removed, depth + 1)
        return
    if not isinstance(node, dict):
        return
    before = len(removed)
    for keyword in _ANTHROPIC_DROPPED:
        if keyword in node:
            _record(node, path, keyword, removed)
    min_items = node.get("minItems")
    if min_items is not None and min_items not in (0, 1):
        _record(node, path, "minItems", removed)
    if node.get("format") not in (None, *ANTHROPIC_FORMATS) and node.get("type") == "string":
        _record(node, path, "format", removed)
    pattern = node.get("pattern")
    if isinstance(pattern, str) and _UNSUPPORTED_REGEX.search(pattern):
        _record(node, path, "pattern", removed)
    enum = node.get("enum")
    if isinstance(enum, list) and any(isinstance(value, dict | list) for value in enum):
        _record(node, path, "enum", removed)
    if "allOf" in node and any(isinstance(part, dict) and "$ref" in part for part in node["allOf"]):
        raise SchemaNotAdaptableError("schema_allof_ref")
    ref = node.get("$ref")
    if isinstance(ref, str) and not ref.startswith("#"):
        raise SchemaNotAdaptableError("schema_external_ref")
    if (node.get("type") == "object" or "properties" in node) and node.get("additionalProperties") is not False:
        removed.append(Removal(path, "additionalProperties", node.get("additionalProperties", True)))
        node["additionalProperties"] = False
    _describe(node, removed[before:])
    for key, value in list(node.items()):
        if key in ("properties", "$defs", "definitions", "patternProperties") and isinstance(value, dict):
            for name, child in value.items():
                _adapt_anthropic(child, f"{path}/{key}/{name}", removed, depth + 1)
        elif key in _SUBSCHEMA_KEYS:
            _adapt_anthropic(value, f"{path}/{key}", removed, depth + 1)


def _check_refs(schema: dict[str, Any]) -> None:
    """Reject a ``$ref`` cycle (a recursive schema): the provider refuses it and no removal fixes it."""
    graph: dict[str, set[str]] = {}

    def refs_in(node: Any) -> set[str]:
        found: set[str] = set()
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "$ref" and isinstance(value, str):
                    found.add(value)
                else:
                    found |= refs_in(value)
        elif isinstance(node, list):
            for value in node:
                found |= refs_in(value)
        return found

    for container in ("$defs", "definitions"):
        definitions = schema.get(container)
        if isinstance(definitions, dict):
            for name, node in definitions.items():
                graph[f"#/{container}/{name}"] = refs_in(node)
    if not graph:
        return
    state: dict[str, int] = {}

    def visit(name: str) -> None:
        if state.get(name) == 1:
            raise SchemaNotAdaptableError("schema_recursive")
        if state.get(name) == 2:
            return
        state[name] = 1
        for target in graph.get(name, ()):
            if target == "#":
                raise SchemaNotAdaptableError("schema_recursive")
            visit(target)
        state[name] = 2

    for name in graph:
        visit(name)
