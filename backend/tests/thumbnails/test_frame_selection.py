"""Which moment of a recording becomes its thumbnail."""

from __future__ import annotations

import math

import pytest

from app.thumbnails.ffmpeg import frame_time_candidates, select_frame_time


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        (3600.0, 600.0),
        (601.0, 600.0),
        (600.0, 600.0),
        (599.0, 299.5),
        (60.0, 30.0),
        (12.0, 6.0),
        (0.5, 0.25),
    ],
)
def test_minute_ten_or_the_middle_of_a_shorter_recording(duration: float, expected: float) -> None:
    assert select_frame_time(duration) == expected


@pytest.mark.parametrize("duration", [None, 0, 0.0, -5.0, math.nan, math.inf])
def test_unknown_or_unusable_duration_has_no_chosen_time(duration: float | None) -> None:
    assert select_frame_time(duration) is None


def test_candidates_start_with_the_chosen_time_and_end_at_the_start_of_the_media() -> None:
    assert frame_time_candidates(3600.0) == [600.0, 1800.0, 0.0]
    assert frame_time_candidates(100.0) == [50.0, 0.0]


def test_candidates_for_an_unknown_duration_try_minute_ten_then_the_start() -> None:
    assert frame_time_candidates(None) == [600.0, 0.0]
    assert frame_time_candidates(0) == [600.0, 0.0]


def test_candidates_are_bounded() -> None:
    assert len(frame_time_candidates(5000.0)) <= 3
