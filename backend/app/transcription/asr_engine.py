"""Common ASREngine interface and data types for transcription.

Defines the provider-agnostic abstraction (Req. 5.1) and the data types
shared by every implementation.
"""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.engines.routing import Route


def default_language() -> str:
    language = os.environ.get("SAURI_DEFAULT_LANGUAGE", "es")
    if re.fullmatch(r"auto|[a-z]{2}", language) is None:
        raise ValueError("SAURI_DEFAULT_LANGUAGE must be a two-letter lowercase code or auto")
    return language


class EngineContractError(ValueError):
    """The engine returned an incompatible or invalid wire contract."""


@dataclass
class EngineInfo:
    name: str
    model: str
    device: str


@dataclass
class TranscriptionWord:
    text: str
    start_ms: int
    end_ms: int
    probability: float | None = None
    timing_repaired: bool = False


@dataclass
class TranscriptionOptions:
    """Options for audio transcription."""

    preferred_language: str = field(default_factory=default_language)
    # Route resolved by the worker for this attempt; None is the default local engine (no header sent).
    route: Route | None = None


@dataclass
class TranscriptionSegment:
    """Text segment with timestamps relative to the start of the audio."""

    text: str
    start_ms: int
    end_ms: int


@dataclass
class TranscriptionResult:
    """Result produced by an ASREngine."""

    segments: list[TranscriptionSegment] = field(default_factory=list)
    language: str = "es"
    supports_turns: bool = False
    words: list[TranscriptionWord] = field(default_factory=list)
    engine: EngineInfo | None = None
    contract_version: int = 2
    diagnostics: dict[str, object] = field(default_factory=dict)
    inverted_words: int = 0


@dataclass
class ASRCapabilities:
    """Capabilities declared by a transcription provider."""

    supports_turns: bool
    is_local: bool


class ASREngine(ABC):
    """Common ASREngine (Automatic Speech Recognition) interface.

    The Meeting_Service interacts with the ASREngine only through this
    interface, independent of the concrete provider (Req. 5.1).
    """

    @abstractmethod
    async def transcribe(
        self, audio_ref: str, options: TranscriptionOptions
    ) -> TranscriptionResult:
        """Transcribes the referenced audio with the given options.

        Args:
            audio_ref: Reference to the audio recording in the ObjectStore.
            options: Transcription configuration (language, etc.).

        Returns:
            TranscriptionResult with segments, language, and the turns flag.
        """
        ...

    @abstractmethod
    def capabilities(self) -> ASRCapabilities:
        """Declares the provider's capabilities.

        Returns:
            ASRCapabilities indicating turn support and whether it's local.
        """
        ...
