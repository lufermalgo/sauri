"""Every cause the summary worker can store has Spanish text, and the provider key no longer reaches the worker."""

from pathlib import Path

import pytest
from sauri_engine_common.external.errors import ERROR_CODES

from app.copy.summary_failures_es import SUMMARY_FAILURE_MESSAGES, summary_failure_message

BACKEND = Path(__file__).resolve().parents[2]
# Classes the summary process cannot produce: audio and word timing belong to the other processes.
NOT_SUMMARY = {"no_word_timestamps"}


def test_every_provider_class_a_summary_can_fail_with_has_text() -> None:
    assert set(SUMMARY_FAILURE_MESSAGES) >= (ERROR_CODES - NOT_SUMMARY)
    for cause in ("context_exceeded", "summary_invalid", "llm_unavailable"):
        assert summary_failure_message(cause)


@pytest.mark.parametrize("cause", [None, "", "made_up"])
def test_an_unknown_cause_has_no_text(cause: str | None) -> None:
    assert summary_failure_message(cause) is None


def test_texts_never_name_a_key_or_carry_placeholders() -> None:
    for text in SUMMARY_FAILURE_MESSAGES.values():
        assert text.endswith(".") and "{" not in text and "sk-" not in text


def test_the_provider_key_file_setting_is_gone_from_the_app_and_the_worker_service() -> None:
    offenders = [
        str(path.relative_to(BACKEND)) for path in (BACKEND / "app").rglob("*.py")
        if "SUMMARIZATION_API_KEY_FILE" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
    compose = (BACKEND.parent / "docker-compose.yml").read_text(encoding="utf-8")
    assert "SUMMARIZATION_API_KEY_FILE" not in compose
