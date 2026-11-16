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


def vad_enabled() -> bool:
    value = os.environ.get("SAURI_ASR_VAD", "on")
    if value not in {"on", "off"}:
        raise ValueError("SAURI_ASR_VAD must be on or off")
    return value == "on"


def default_prompt_enabled() -> bool:
    value = os.environ.get("SAURI_ASR_DEFAULT_PROMPT", "on")
    if value not in {"on", "off"}:
        raise ValueError("SAURI_ASR_DEFAULT_PROMPT must be on or off")
    return value == "on"


def vad_threshold() -> float:
    value = float(os.environ.get("SAURI_ASR_VAD_THRESHOLD", "0.5"))
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("SAURI_ASR_VAD_THRESHOLD must be between zero and one inclusive")
    return value


def chunk_ms() -> int:
    value = float(os.environ.get("SAURI_ASR_CHUNK_SECONDS", "120"))
    if not math.isfinite(value * 1000) or value < 0.001:
        raise ValueError("SAURI_ASR_CHUNK_SECONDS must be positive and at least 0.001")
    return round(value * 1000)


def suppress_nst() -> bool:
    value = os.environ.get("SAURI_ASR_SUPPRESS_NST", "off").lower()
    if value not in {"on", "off", "true", "false", "1", "0"}:
        raise ValueError("Invalid SAURI_ASR_SUPPRESS_NST")
    return value in {"on", "true", "1"}
