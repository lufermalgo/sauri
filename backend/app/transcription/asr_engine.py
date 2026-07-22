"""Common ASREngine interface and data types for transcription.

Defines the provider-agnostic abstraction (Req. 5.1) and the data types
shared by every implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class TranscriptionOptions:
    """Options for audio transcription."""

    preferred_language: str = "es-CO"


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
    language: str = "es-CO"
    supports_turns: bool = False


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
