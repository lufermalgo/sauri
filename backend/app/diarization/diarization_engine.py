"""Common DiarizationEngine interface and data types for diarization.

Defines the provider-agnostic abstraction (Req. 2.7) and the data types
shared by every implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class EngineContractError(ValueError):
    """The engine returned an incompatible or invalid wire contract."""


@dataclass
class EngineInfo:
    name: str
    model: str
    device: str


@dataclass
class DiarizationOptions:
    """Options for audio diarization.

    Attributes:
        duration_ms: Recording duration in milliseconds; lets the engine
            bound the end_ms of segments (Req. 5.4). None if unknown.
    """

    duration_ms: int | None = None


@dataclass
class SpeakerSegment:
    """Timed unit produced by the DiarizationEngine.

    Indicates that a speaker (identified by raw_label) was active during
    the interval [start_ms, end_ms] (Req. 5.2, 5.3).
    """

    raw_label: str
    start_ms: int
    end_ms: int


@dataclass
class DiarizationResult:
    """Result produced by a DiarizationEngine.

    The segment list is sorted ascending by start_ms in __post_init__
    (Req. 5.1). speaker_count reflects the number of distinct raw labels
    (Req. 5.5).
    """

    segments: list[SpeakerSegment] = field(default_factory=list)
    speaker_count: int = 0
    engine: EngineInfo | None = None
    contract_version: int = 2

    def __post_init__(self) -> None:
        """Sorts segments by ascending start_ms (Property 6)."""
        self.segments = sorted(self.segments, key=lambda s: s.start_ms)


@dataclass
class DiarizationCapabilities:
    """Capabilities declared by a diarization provider (Req. 8.4)."""

    is_local: bool
    provider_name: str


class DiarizationEngine(ABC):
    """Common DiarizationEngine interface.

    The Diarization_Worker interacts with the DiarizationEngine only
    through this interface, independent of the concrete provider (Req. 2.7).
    """

    @abstractmethod
    async def diarize(
        self, audio_ref: str, options: DiarizationOptions
    ) -> DiarizationResult:
        """Diarizes the referenced audio with the given options.

        Args:
            audio_ref: Reference to the audio recording in the ObjectStore.
            options: Diarization configuration (duration, etc.).

        Returns:
            DiarizationResult with ordered segments and speaker_count.
        """
        ...

    @abstractmethod
    def capabilities(self) -> DiarizationCapabilities:
        """Declares the provider's capabilities.

        Returns:
            DiarizationCapabilities indicating whether it's local and the
            provider's name.
        """
        ...
