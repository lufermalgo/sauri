"""Native request language compatibility and the end-to-end HTTP budget."""

from __future__ import annotations

import math
import os
import re
import time


def default_language() -> str:
    language = os.environ.get("SAURI_DEFAULT_LANGUAGE", "es")
    if re.fullmatch(r"auto|[a-z]{2}", language) is None:
        raise ValueError("SAURI_DEFAULT_LANGUAGE must be a two-letter lowercase code or auto")
    return language


def language_code(language: str) -> str:
    # Accept legacy region hints at the engine boundary, but never three-letter codes.
    if re.fullmatch(r"[a-z]{2}-[A-Z]{2}", language):
        return language[:2]
    if re.fullmatch(r"auto|[a-z]{2}", language) is None:
        raise ValueError("invalid_language")
    return language


def server_budget() -> float:
    client_timeout = float(os.environ.get("ASR_TIMEOUT_SECONDS", "3600"))
    if not math.isfinite(client_timeout) or client_timeout <= 0:
        raise ValueError("ASR_TIMEOUT_SECONDS must be a positive finite number")
    # Leave response/transport headroom inside the client's configured timeout.
    return client_timeout - min(30.0, client_timeout * 0.1)


def remaining(deadline: float) -> float:
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError("engine_failed")
    return seconds
