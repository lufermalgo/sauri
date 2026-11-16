"""Closed set of classified provider errors and the total ``classify`` function.

Error values carry only a class code, never request or response content, so they are safe to log
and to return to callers.
"""

from __future__ import annotations

import math
from typing import Final

# code -> retryable (design.md, "Manejo de Errores")
RETRYABLE: Final[dict[str, bool]] = {
    "provider_auth": False,
    "provider_quota": True,
    "provider_rate_limited": True,
    "provider_timeout": True,
    "provider_unavailable": True,
    "provider_bad_request": False,
    "provider_invalid_output": False,
    "provider_context_exceeded": False,
    "provider_unsupported": False,
    "audio_too_large": False,
    "no_word_timestamps": False,
    "consent_missing": False,
    "origin_mismatch": False,
    "secret_unavailable": False,
}
ERROR_CODES: Final[frozenset[str]] = frozenset(RETRYABLE)

MAX_RETRY_AFTER_S: Final = 3600

_CONTEXT_MARKERS: Final = (
    "context_exceeded",
    "context_length_exceeded",
    "exceed_context_size",
    "exceeds the available context",
    "maximum context length",
)
_QUOTA_MARKERS: Final = ("insufficient_quota", "billing", "credit_balance", "quota_exceeded")


class ProviderError(Exception):
    """A classified failure. ``str(error)`` is the class code only."""

    def __init__(self, code: str, *, retry_after_s: int | None = None, reason: str | None = None) -> None:
        if code not in ERROR_CODES:
            raise ValueError("unknown_error_code")
        super().__init__(code)
        self.code = code
        self.retryable = RETRYABLE[code]
        self.retry_after_s = retry_after_s
        # Short machine-readable sub-code (for example ``route_too_large``); never content.
        self.reason = reason

    def to_payload(self) -> dict[str, dict[str, object]]:
        """Body returned by gateways: ``{"error": {"code", "retryable", "retry_after_s"}}``."""
        return {"error": {"code": self.code, "retryable": self.retryable, "retry_after_s": self.retry_after_s}}


def parse_retry_after(value: str | None) -> int | None:
    """Seconds from a ``Retry-After`` header; HTTP dates and invalid values yield ``None``."""
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return min(math.ceil(seconds), MAX_RETRY_AFTER_S)


def _has(hint: str, markers: tuple[str, ...]) -> bool:
    return any(marker in hint for marker in markers)


def _classify_exception(exc: BaseException) -> ProviderError:
    # Timeouts first: httpx timeouts are also transport errors. They are matched by class name so this
    # module needs no httpx import (not every native venv ships it). Everything else is a cut connection.
    name_chain = {cls.__name__ for cls in type(exc).__mro__}
    if isinstance(exc, TimeoutError) or "TimeoutException" in name_chain:
        return ProviderError("provider_timeout")
    return ProviderError("provider_unavailable")


def classify(
    status: int | None,
    body_hint: str | None = None,
    exc: BaseException | None = None,
    *,
    retry_after: str | None = None,
) -> ProviderError:
    """Reduce any HTTP status, transport exception and body hint to exactly one error class.

    ``body_hint`` is a short error code or type taken from the provider response (never content).
    A status wins over an exception; with neither, the provider is treated as unavailable.
    """
    hint = (body_hint or "").lower()
    if status is None:
        return _classify_exception(exc) if exc is not None else ProviderError("provider_unavailable")
    if _has(hint, _CONTEXT_MARKERS):
        return ProviderError("provider_context_exceeded")
    if status in (401, 403):
        return ProviderError("provider_auth")
    if status == 402:
        return ProviderError("provider_quota")
    if status == 429:
        if _has(hint, _QUOTA_MARKERS):
            return ProviderError("provider_quota")
        return ProviderError("provider_rate_limited", retry_after_s=parse_retry_after(retry_after))
    if status in (408, 504, 524):
        return ProviderError("provider_timeout")
    if status == 413:
        return ProviderError("audio_too_large")
    if status >= 500:
        return ProviderError("provider_unavailable", retry_after_s=parse_retry_after(retry_after))
    # Remaining 1xx-4xx: bad parameters, unexpected redirects (never followed) or unexpected statuses.
    return ProviderError("provider_bad_request")
