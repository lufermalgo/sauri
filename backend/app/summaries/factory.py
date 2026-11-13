"""Fail-closed configuration for the local Ollama summary provider."""

from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

from app.summaries.engine import OllamaSummarizationEngine

_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*\Z")


def create_summarization_engine() -> OllamaSummarizationEngine:
    url = os.getenv("SUMMARIZATION_OLLAMA_URL", "")
    model = os.getenv("SUMMARIZATION_OLLAMA_MODEL", "")
    try:
        parsed = urlsplit(url)
        valid_url = (
            parsed.scheme == "http"
            and bool(parsed.hostname)
            and parsed.port is not None
            and not parsed.username
            and not parsed.password
            and parsed.path in ("", "/")
            and not parsed.query
            and not parsed.fragment
            and not any(char.isspace() for char in url)
        )
    except ValueError:
        valid_url = False
    if not valid_url:
        raise ValueError("SUMMARIZATION_OLLAMA_URL must be a local HTTP endpoint URL with a port")
    if _MODEL.fullmatch(model) is None:
        raise ValueError("SUMMARIZATION_OLLAMA_MODEL must name the installed local model")
    try:
        timeout_seconds = float(os.getenv("SUMMARIZATION_TIMEOUT_SECONDS", "900"))
    except ValueError:
        raise ValueError("SUMMARIZATION_TIMEOUT_SECONDS must be finite and positive") from None
    return OllamaSummarizationEngine(url.rstrip("/"), model, timeout_seconds=timeout_seconds)
