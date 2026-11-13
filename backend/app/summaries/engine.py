"""Local Ollama adapter behind the provider-independent summary generation contract."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from contextlib import suppress
from datetime import UTC, datetime
from typing import Protocol

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_USAGE_COUNTS = ("prompt_eval_count", "eval_count")
_USAGE_DURATIONS = ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration")


def _record_generation(started: float, outcome: str, envelope: object) -> None:
    """Emit only allowlisted numeric usage, never provider content or exception messages."""
    event: dict[str, object] = {
        "schema_version": 1,
        "timestamp": datetime.now(UTC).isoformat(),
        "operation": "summary.generate",
        "provider": "ollama",
        "outcome": outcome,
        "duration_seconds": time.perf_counter() - started,
    }
    if isinstance(envelope, dict):
        for name in _USAGE_COUNTS:
            value = envelope.get(name)
            if type(value) is int and 0 <= value <= 2**63 - 1:
                event[name] = value
        for name in _USAGE_DURATIONS:
            value = envelope.get(name)
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and 0 <= value <= 2**63 - 1
                and math.isfinite(value)
            ):
                event[f"{name}_seconds"] = value / 1_000_000_000
    # Observability must not turn a successful artifact into a retry or mask a failure.
    with suppress(Exception):
        logger.info(json.dumps(event, allow_nan=False, separators=(",", ":")))


class CanonicalSummary(BaseModel):
    topic: str
    key_points: list[str]


class SummarizationEngine(Protocol):
    async def generate(self, transcript_text: str, instructions_snapshot: str) -> CanonicalSummary: ...


class OllamaSummarizationEngine:
    def __init__(
        self,
        url: str,
        model: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 900.0,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("SUMMARIZATION_TIMEOUT_SECONDS must be finite and positive")
        self.url = url
        self.model = model
        self._client = client
        self.timeout_seconds = timeout_seconds

    async def generate(self, transcript_text: str, instructions_snapshot: str) -> CanonicalSummary:
        # The snapshot is opaque: no template grammar, identity or media is sent.
        prompt = (
            "Generate the main topic and key points for this transcript as JSON. "
            "Apply the following template instructions to both elements.\n"
            f"Template instructions:\n{instructions_snapshot}\n"
            f"Transcript:\n{transcript_text}"
        )
        request = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": CanonicalSummary.model_json_schema(),
        }
        # Non-streaming Ollama sends no response while evaluating the transcript.
        # Bound the whole attempt as well as HTTP inactivity; keep connection failures fast.
        timeout = httpx.Timeout(self.timeout_seconds, connect=10.0)
        started = time.perf_counter()
        envelope: object = None
        outcome = "error"
        try:
            async with asyncio.timeout(self.timeout_seconds):
                if self._client is None:
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        response = await client.post(f"{self.url}/api/generate", json=request)
                else:
                    response = await self._client.post(f"{self.url}/api/generate", json=request, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            envelope = data
            result = CanonicalSummary.model_validate_json(data["response"])
            outcome = "succeeded"
            return result
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except (TimeoutError, httpx.TimeoutException):
            outcome = "timeout"
            raise
        finally:
            _record_generation(started, outcome, envelope)
