"""Lossless, timed transcript windows and citation validation."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError


@dataclass(frozen=True)
class Turn:
    text: str
    start_ms: int
    end_ms: int
    speaker: str = "Speaker ?"


@dataclass(frozen=True)
class Passage:
    passage_id: str
    start_ms: int
    end_ms: int
    turns: tuple[Turn, ...]

    def render(self) -> str:
        def timestamp(ms: int) -> str:
            seconds = ms // 1000
            return f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"

        text = "\n".join(f"{turn.speaker}: {turn.text}" for turn in self.turns)
        return f"[{self.passage_id} {timestamp(self.start_ms)}–{timestamp(self.end_ms)}] {text}"


class PassageRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passage_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)


class KeyPoint(BaseModel):
    """Stored shape of schema v1 (flat point). Only read, never written."""

    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    sources: list[PassageRef] = Field(min_length=1, max_length=2)


class SummaryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=800)
    sub_items: list[Annotated[str, StringConstraints(min_length=1, max_length=500)]] = Field(
        default_factory=list, max_length=8,
    )


class KeyPointBlock(BaseModel):
    """One thematic block of the schema v2 summary."""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=160)
    items: list[SummaryItem] = Field(min_length=1, max_length=12)
    sources: list[PassageRef] = Field(min_length=1, max_length=4)


class CanonicalSummary(BaseModel):
    """Schema v2: topic paragraph, thematic blocks and a closing conclusion."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[2] = 2
    topic: str = Field(min_length=1, max_length=1200)
    key_points: list[KeyPointBlock] = Field(min_length=1, max_length=12)
    conclusion: str = Field(min_length=1, max_length=1200)
    review_state: Literal["draft"] = "draft"


@dataclass(frozen=True)
class StoredSummaryContent:
    """Key points and conclusion read back from the stored JSON, whatever the schema version."""

    schema_version: int
    key_points: list[Any]
    conclusion: str | None


def encode_key_points(summary: CanonicalSummary) -> str:
    """The `key_points_json` payload: a v2 object. Schema v1 stored a bare list instead."""
    return json.dumps(
        {
            "schema_version": summary.schema_version,
            "key_points": [block.model_dump() for block in summary.key_points],
            "conclusion": summary.conclusion,
        },
        ensure_ascii=False,
    )


def decode_key_points(payload: str) -> StoredSummaryContent:
    """Tolerant reader: a bare list is schema v1, an object with `schema_version` 2 is v2."""
    data = json.loads(payload)
    if isinstance(data, list):
        return StoredSummaryContent(1, data, None)
    if isinstance(data, dict) and data.get("schema_version") == 2 and isinstance(data.get("key_points"), list):
        conclusion = data.get("conclusion")
        return StoredSummaryContent(2, data["key_points"], conclusion if isinstance(conclusion, str) else None)
    raise ValueError("Unrecognized stored summary shape")


class SummaryInvalidError(ValueError):
    """No usable grounded summary was returned."""


def build_passages(turns: Sequence[Turn], window_ms: int = 60_000) -> list[Passage]:
    """Keep whole turns in input order, closing a window at the next start boundary."""
    if window_ms <= 0:
        raise ValueError("window_ms must be positive")
    groups: list[list[Turn]] = []
    for turn in turns:
        if turn.start_ms < 0 or turn.end_ms < turn.start_ms:
            raise ValueError("Invalid turn interval")
        if not groups or turn.start_ms >= groups[-1][0].start_ms + window_ms:
            groups.append([])
        groups[-1].append(turn)
    return [
        Passage(f"P{index:04}", min(t.start_ms for t in group), max(t.end_ms for t in group), tuple(group))
        for index, group in enumerate(groups)
    ]


def _max_items(model: type[BaseModel], field: str) -> int:
    """The ``max_length`` the model declares for a list field, so the limits live in one place."""
    for constraint in model.model_fields[field].metadata:
        limit = getattr(constraint, "max_length", None)
        if isinstance(limit, int):
            return limit
    raise LookupError(f"{model.__name__}.{field} has no max_length")  # pragma: no cover - guarded by a test


MAX_KEY_POINTS = _max_items(CanonicalSummary, "key_points")
MAX_ITEMS = _max_items(KeyPointBlock, "items")
MAX_SOURCES = _max_items(KeyPointBlock, "sources")
MAX_SUB_ITEMS = _max_items(SummaryItem, "sub_items")


def _clamp_items(items: Any) -> Any:
    """Cut ``items`` and each item's ``sub_items`` to the schema's caps; anything malformed is left to validation."""
    if not isinstance(items, list):
        return items
    clamped = []
    for item in items[:MAX_ITEMS]:
        if isinstance(item, dict) and isinstance(item.get("sub_items"), list):
            item = {**item, "sub_items": item["sub_items"][:MAX_SUB_ITEMS]}
        clamped.append(item)
    return clamped


def validate_citations(
    summary: CanonicalSummary | dict[str, Any], passages: Sequence[Passage],
) -> CanonicalSummary:
    """Drop invented IDs and unsourced points; derive times from trusted source data.

    Lists longer than the schema allows are cut to its caps first: a provider whose structured output cannot
    enforce ``maxItems`` (Gemini) may answer a little long, and that should not discard an otherwise valid summary.
    Everything else (types, lengths, required fields) is still validated strictly.
    """
    by_id = {passage.passage_id: passage for passage in passages}
    data = summary.model_dump() if isinstance(summary, CanonicalSummary) else summary
    points = []
    try:
        for point in data["key_points"]:
            sources = []
            seen = set()
            for ref in point.get("sources", []):
                if not isinstance(ref, dict) or not isinstance(ref.get("passage_id"), str):
                    continue
                passage = by_id.get(ref["passage_id"])
                if passage is not None and passage.passage_id not in seen:
                    sources.append(PassageRef(
                        passage_id=passage.passage_id, start_ms=passage.start_ms, end_ms=passage.end_ms,
                    ))
                    seen.add(passage.passage_id)
            if sources:
                points.append({**point, "sources": sources[:MAX_SOURCES], "items": _clamp_items(point.get("items"))})
        return CanonicalSummary.model_validate({**data, "key_points": points[:MAX_KEY_POINTS]})
    except (ValidationError, KeyError, TypeError, AttributeError):
        raise SummaryInvalidError("summary_invalid") from None
