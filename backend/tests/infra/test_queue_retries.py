"""Tests for reading/validating retries per topic in queue_rabbitmq.py.

# Feature: speaker-identification
# Task: 12.1 — Write test for reading/validating retries per topic (RED)
# Validates: Requirements 10.2

Verifies that the generalized `_read_max_retries` honors
`DIARIZATION_MAX_RETRIES` for the "diarize" topic (range 0-10, default 3)
without breaking the `ASR_MAX_RETRIES` reading for "transcribe".
"""

from __future__ import annotations

import os
from unittest.mock import patch

from app.infra.queue_rabbitmq import _read_max_retries


class TestReadMaxRetriesDiarize:
    """Tests for _read_max_retries for the 'diarize' topic with DIARIZATION_MAX_RETRIES."""

    def test_explicit_value_5(self) -> None:
        """DIARIZATION_MAX_RETRIES=5 → for topic 'diarize', max retries = 5."""
        with patch.dict(os.environ, {"DIARIZATION_MAX_RETRIES": "5"}, clear=False):
            assert _read_max_retries("diarize") == 5

    def test_default_when_absent(self) -> None:
        """DIARIZATION_MAX_RETRIES absent → default 3 for 'diarize'."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DIARIZATION_MAX_RETRIES", None)
            assert _read_max_retries("diarize") == 3

    def test_value_0_valid(self) -> None:
        """DIARIZATION_MAX_RETRIES=0 → 0 retries (valid)."""
        with patch.dict(os.environ, {"DIARIZATION_MAX_RETRIES": "0"}, clear=False):
            assert _read_max_retries("diarize") == 0

    def test_value_10_valid(self) -> None:
        """DIARIZATION_MAX_RETRIES=10 → 10 retries (valid edge)."""
        with patch.dict(os.environ, {"DIARIZATION_MAX_RETRIES": "10"}, clear=False):
            assert _read_max_retries("diarize") == 10

    def test_value_11_out_of_range(self) -> None:
        """DIARIZATION_MAX_RETRIES=11 → clamped to default 3."""
        with patch.dict(os.environ, {"DIARIZATION_MAX_RETRIES": "11"}, clear=False):
            assert _read_max_retries("diarize") == 3

    def test_negative_value_out_of_range(self) -> None:
        """DIARIZATION_MAX_RETRIES=-1 → clamped to default 3."""
        with patch.dict(os.environ, {"DIARIZATION_MAX_RETRIES": "-1"}, clear=False):
            assert _read_max_retries("diarize") == 3


class TestReadMaxRetriesTranscribeNotBroken:
    """Verifies the generalization doesn't break 'transcribe' behavior."""

    def test_asr_max_retries_still_works(self) -> None:
        """ASR_MAX_RETRIES=2 with topic 'transcribe' → still reads 2."""
        with patch.dict(os.environ, {"ASR_MAX_RETRIES": "2"}, clear=False):
            assert _read_max_retries("transcribe") == 2
