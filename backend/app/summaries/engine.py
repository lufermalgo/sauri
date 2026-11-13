"""Local Ollama adapter behind the provider-independent summary generation contract."""

from __future__ import annotations

import asyncio
import math
from typing import Protocol

import httpx
from pydantic import BaseModel


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
        async with asyncio.timeout(self.timeout_seconds):
            if self._client is None:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(f"{self.url}/api/generate", json=request)
            else:
                response = await self._client.post(f"{self.url}/api/generate", json=request, timeout=timeout)
        response.raise_for_status()
        return CanonicalSummary.model_validate_json(response.json()["response"])
