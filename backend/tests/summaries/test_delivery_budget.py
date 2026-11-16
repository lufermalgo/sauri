"""One summary delivery must always finish before RabbitMQ's consumer_timeout."""

import pytest

from app.infra.engine_slot import (
    BROKER_CONSUMER_TIMEOUT_S,
    ENGINE_CALL_TIMEOUT_S,
    SLOT_WAIT_TIMEOUT_S,
    SUMMARY_ENGINE_CALL_TIMEOUT_S,
)
from app.summaries import worker
from app.summaries.factory import create_summarization_engine

SAFETY_MARGIN_S = 30.0  # SQL, confirmed publication and acknowledgement


def test_summary_delivery_budget_is_below_broker_consumer_timeout() -> None:
    assert SLOT_WAIT_TIMEOUT_S + SUMMARY_ENGINE_CALL_TIMEOUT_S + SAFETY_MARGIN_S < BROKER_CONSUMER_TIMEOUT_S
    assert worker.ENGINE_CALL_TIMEOUT_S == SUMMARY_ENGINE_CALL_TIMEOUT_S
    # The other heavy engines keep their own, shorter hard limit.
    assert ENGINE_CALL_TIMEOUT_S == 1200.0


def test_default_client_budget_fits_the_worker_hard_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUMMARIZATION_BASE_URL", "http://localhost:11434")
    monkeypatch.delenv("SUMMARIZATION_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr("app.summaries.factory.Path.read_text", lambda *_a, **_k: "synthetic-token")
    engine = create_summarization_engine()
    assert engine.timeout_seconds < SUMMARY_ENGINE_CALL_TIMEOUT_S
    assert SLOT_WAIT_TIMEOUT_S + engine.timeout_seconds + SAFETY_MARGIN_S < BROKER_CONSUMER_TIMEOUT_S
