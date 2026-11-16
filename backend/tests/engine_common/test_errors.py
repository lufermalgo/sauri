"""Property 11: every (status, transport exception, body hint) maps to exactly one classified error."""

from __future__ import annotations

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st
from sauri_engine_common.external.errors import (
    ERROR_CODES,
    MAX_RETRY_AFTER_S,
    RETRYABLE,
    ProviderError,
    classify,
    parse_retry_after,
)

CONTEXT_HINTS = ["context_length_exceeded", "Exceeds the available context size", "maximum context length is 8192"]
EXCEPTIONS: list[BaseException | None] = [
    None,
    httpx.ConnectTimeout("t"),
    httpx.ReadTimeout("t"),
    httpx.PoolTimeout("t"),
    httpx.ConnectError("c"),
    httpx.ReadError("r"),
    httpx.RemoteProtocolError("p"),
    TimeoutError(),
    ConnectionResetError(),
    OSError("o"),
    ValueError("v"),
    RuntimeError("r"),
]
statuses = st.one_of(st.none(), st.integers(min_value=-5, max_value=700))
hints = st.one_of(st.none(), st.text(max_size=80), st.sampled_from(CONTEXT_HINTS))
retry_after_values = st.one_of(st.none(), st.text(max_size=12), st.integers(-5, 10**9).map(str))


@given(statuses, hints, st.sampled_from(EXCEPTIONS), retry_after_values)
def test_classification_is_total_and_consistent(
    status: int | None, hint: str | None, exc: BaseException | None, retry_after: str | None
) -> None:
    error = classify(status, hint, exc, retry_after=retry_after)
    assert isinstance(error, ProviderError)
    assert error.code in ERROR_CODES
    assert error.retryable is RETRYABLE[error.code]
    assert str(error) == error.code
    assert error.retry_after_s is None or 0 <= error.retry_after_s <= MAX_RETRY_AFTER_S


@given(st.sampled_from([401, 403]), st.text(max_size=40).filter(lambda text: "context" not in text.lower()))
def test_auth_failures_are_not_retryable(status: int, hint: str) -> None:
    error = classify(status, hint)
    assert (error.code, error.retryable) == ("provider_auth", False)


@given(st.integers(0, 3600))
def test_rate_limit_is_retryable_and_keeps_retry_after(seconds: int) -> None:
    error = classify(429, None, retry_after=str(seconds))
    assert (error.code, error.retryable, error.retry_after_s) == ("provider_rate_limited", True, seconds)


def test_rate_limit_without_a_usable_header() -> None:
    assert classify(429).retry_after_s is None
    assert classify(429, retry_after="Wed, 21 Oct 2026 07:28:00 GMT").retry_after_s is None
    assert classify(429, retry_after="1e12").retry_after_s == MAX_RETRY_AFTER_S


def test_quota_exhaustion_is_retryable_for_the_local_fallback() -> None:
    assert classify(402).code == "provider_quota"
    assert classify(429, "insufficient_quota").code == "provider_quota"
    assert classify(402).retryable is True


@given(st.integers(500, 599).filter(lambda status: status not in (504, 524)))
def test_server_errors_are_retryable(status: int) -> None:
    error = classify(status)
    assert (error.code, error.retryable) == ("provider_unavailable", True)


def test_gateway_timeout_statuses_are_timeouts() -> None:
    assert {classify(status).code for status in (408, 504, 524)} == {"provider_timeout"}


@given(st.integers(100, 599), st.sampled_from(CONTEXT_HINTS))
def test_context_overflow_is_never_retryable(status: int, hint: str) -> None:
    error = classify(status, hint)
    assert (error.code, error.retryable) == ("provider_context_exceeded", False)


def test_transport_exceptions() -> None:
    timeouts: list[BaseException] = [httpx.ConnectTimeout("t"), httpx.ReadTimeout("t"), TimeoutError()]
    for timeout in timeouts:
        assert classify(None, None, timeout).code == "provider_timeout"
    cut: list[BaseException] = [
        httpx.ConnectError("c"), httpx.RemoteProtocolError("p"), ConnectionResetError(), RuntimeError("x"),
    ]
    for cause in cut:
        error = classify(None, None, cause)
        assert (error.code, error.retryable) == ("provider_unavailable", True)
    assert classify(None).code == "provider_unavailable"


def test_a_status_wins_over_an_exception() -> None:
    assert classify(401, None, httpx.ConnectError("c")).code == "provider_auth"


def test_other_client_errors_and_redirects_are_bad_requests() -> None:
    for status in (200, 301, 302, 400, 404, 409, 422):
        error = classify(status)
        assert (error.code, error.retryable) == ("provider_bad_request", False)
    assert classify(413).code == "audio_too_large"


def test_error_values_never_carry_content() -> None:
    error = classify(400, "SECRET-BODY-TEXT sk-live-123")
    assert "SECRET" not in str(error) and "SECRET" not in repr(error) and "SECRET" not in str(error.to_payload())


def test_payload_shape_and_unknown_codes() -> None:
    assert ProviderError("provider_rate_limited", retry_after_s=7).to_payload() == {
        "error": {"code": "provider_rate_limited", "retryable": True, "retry_after_s": 7}
    }
    with pytest.raises(ValueError):
        ProviderError("made_up")


@given(st.text(max_size=20))
def test_retry_after_parsing_never_raises(value: str) -> None:
    result = parse_retry_after(value)
    assert result is None or 0 <= result <= MAX_RETRY_AFTER_S
