"""Lossless, timed transcript windows and citation validation."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


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
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    sources: list[PassageRef] = Field(min_length=1, max_length=2)


class CanonicalSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str = Field(min_length=1, max_length=450)
    key_points: list[KeyPoint] = Field(min_length=1, max_length=12)
    review_state: Literal["draft"] = "draft"


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


def validate_citations(
    summary: CanonicalSummary | dict[str, Any], passages: Sequence[Passage],
) -> CanonicalSummary:
    """Drop invented IDs and unsourced points; derive times from trusted source data."""
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
                points.append({**point, "sources": sources[:2]})
        return CanonicalSummary.model_validate({**data, "key_points": points[:12]})
    except (ValidationError, KeyError, TypeError, AttributeError):
        raise SummaryInvalidError("summary_invalid") from None
