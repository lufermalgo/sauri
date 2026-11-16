"""Configuration of the summary client: the local gateway and its engine token (file only)."""

from __future__ import annotations

import math
import os
import re
from contextlib import suppress
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from app.infra.engine_slot import SUMMARY_ENGINE_CALL_TIMEOUT_S
from app.summaries.engine import OpenAICompatibleSummarizationEngine

_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*\Z")


def create_summarization_engine() -> OpenAICompatibleSummarizationEngine:
    url = os.getenv("SUMMARIZATION_BASE_URL", "http://host.docker.internal:8003/v1")
    model = os.getenv("SUMMARIZATION_MODEL", "qwen3.5-9b")
    try:
        parsed = urlsplit(url)
        valid_url = (
            parsed.scheme in ("http", "https") and bool(parsed.hostname)
            and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment
            and not any(char.isspace() for char in url)
        )
        _ = parsed.port
    except ValueError:
        valid_url = False
    if not valid_url:
        raise ValueError("SUMMARIZATION_BASE_URL must be an HTTP(S) base URL without credentials")
    if _MODEL.fullmatch(model) is None:
        raise ValueError("SUMMARIZATION_MODEL must name a model")
    try:
        timeout_seconds = float(os.getenv("SUMMARIZATION_TIMEOUT_SECONDS", "1500"))
    except ValueError:
        raise ValueError("SUMMARIZATION_TIMEOUT_SECONDS must be finite and positive") from None
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("SUMMARIZATION_TIMEOUT_SECONDS must be finite and positive")
    # The client waits for the gateway's cold start (120 s) plus 5 s for the HTTP response.
    client_timeout_seconds = timeout_seconds + 120.0 + 5.0
    if client_timeout_seconds > SUMMARY_ENGINE_CALL_TIMEOUT_S:
        # Otherwise the worker would cut the call short, or the broker would drop the delivery.
        raise ValueError(
            "SUMMARIZATION_TIMEOUT_SECONDS must be at most "
            f"{SUMMARY_ENGINE_CALL_TIMEOUT_S - 125.0:g} to finish within the broker consumer timeout"
        )
    hostname = (parsed.hostname or "").rstrip(".").lower()
    is_local = hostname in ("localhost", "host.docker.internal")
    with suppress(ValueError):
        is_local = is_local or ip_address(hostname).is_loopback
    if not is_local:
        # A provider key never reaches this process: external providers are chosen in Settings and called by the
        # host gateway with a key from the host secret store (X-Sauri-Route).
        raise ValueError("SUMMARIZATION_BASE_URL must point to the local engine gateway")
    token_file = Path(os.getenv("SAURI_ENGINE_TOKEN_FILE", Path.home() / ".config/sauri/engine_token"))
    try:
        api_key = token_file.read_text(encoding="utf-8").strip()
        if not api_key or any(c.isspace() for c in api_key) or not api_key.isascii():
            raise ValueError
    except (OSError, ValueError):
        raise ValueError("SAURI_ENGINE_TOKEN_FILE must contain a readable nonempty credential") from None
    # The environment variable is the gateway's inference budget; the client adds its cold start.
    return OpenAICompatibleSummarizationEngine(
        url, model, api_key=api_key, timeout_seconds=client_timeout_seconds,
    )
