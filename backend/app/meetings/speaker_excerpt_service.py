"""Derive and resolve opaque, scope-bound speaker excerpt references."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.auth.token import JWT_SECRET


class ExcerptCandidate(Protocol):
    """A diarization interval with its speaker assignment and VAD evidence."""

    start_ms: int
    end_ms: int
    vad_positive_windows: int
    vad_window_count: int
    assigned_speaker_id: str


@dataclass(frozen=True)
class SpeakerExcerpt:
    """Validated excerpt metadata and its opaque persisted reference value."""

    start_ms: int
    end_ms: int
    reference: str

    def public_dict(self) -> dict[str, int | str]:
        """Return only fields suitable for persistence or an API response."""
        return {"start_ms": self.start_ms, "end_ms": self.end_ms, "reference": self.reference}


class SpeakerExcerptService:
    """Select validated intervals and encrypt their private source locator.

    The returned reference is intended to be persisted in the review item. Its
    authenticated encryption contains the server-side object locator and scope;
    callers must still authorize recording access before invoking ``play``.
    """

    def __init__(self, *, decode_interval, read_interval) -> None:
        self._decode_interval = decode_interval
        self._read_interval = read_interval
        self._cipher = AESGCM(hashlib.sha256(JWT_SECRET.encode("utf-8")).digest())

    def derive(
        self,
        *,
        recording_id: str,
        revision_id: str,
        speaker_id: str,
        object_key: str,
        audio_duration_ms: int,
        candidates: list[ExcerptCandidate],
    ) -> SpeakerExcerpt:
        """Return the highest-ranked candidate that passes all validations."""
        if audio_duration_ms <= 0 or not all((recording_id, revision_id, speaker_id, object_key)):
            raise ValueError("recording, revision, speaker and duration are required")

        ordered = sorted(
            candidates,
            key=lambda candidate: (
                -(candidate.end_ms - candidate.start_ms),
                -(candidate.vad_positive_windows / candidate.vad_window_count)
                if candidate.vad_window_count > 0
                else 0,
                candidate.start_ms,
            ),
        )
        for candidate in ordered:
            if (
                candidate.assigned_speaker_id != speaker_id
                or candidate.start_ms < 0
                or candidate.end_ms <= candidate.start_ms
                or candidate.end_ms > audio_duration_ms
                or candidate.vad_window_count <= 0
                or candidate.vad_positive_windows <= 0
                or candidate.vad_positive_windows > candidate.vad_window_count
            ):
                continue
            try:
                decoded = self._decode_interval(object_key, candidate.start_ms, candidate.end_ms)
            except (ValueError, OSError):
                continue
            if not decoded:
                continue
            payload = json.dumps(
                {
                    "recording_id": recording_id,
                    "revision_id": revision_id,
                    "speaker_id": speaker_id,
                    "object_key": object_key,
                    "start_ms": candidate.start_ms,
                    "end_ms": candidate.end_ms,
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            nonce = secrets.token_bytes(12)
            ciphertext = self._cipher.encrypt(nonce, payload, b"sauri-speaker-excerpt-v1")
            reference = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii").rstrip("=")
            return SpeakerExcerpt(candidate.start_ms, candidate.end_ms, reference)

        raise ValueError("no validated speaker excerpt")

    def resolve(
        self,
        reference: str,
        *,
        recording_id: str,
        revision_id: str,
        speaker_id: str,
    ) -> tuple[str, int, int]:
        """Resolve only a well-formed reference for its exact source scope."""
        try:
            encoded = reference.encode("ascii")
            padded = encoded + b"=" * (-len(encoded) % 4)
            token = base64.urlsafe_b64decode(padded)
            if len(token) <= 12:
                raise ValueError("invalid excerpt reference")
            payload = self._cipher.decrypt(token[:12], token[12:], b"sauri-speaker-excerpt-v1")
            data = json.loads(payload)
        except (ValueError, UnicodeError, json.JSONDecodeError, InvalidTag) as error:
            raise LookupError("unknown excerpt reference") from error

        if (
            data.get("recording_id") != recording_id
            or data.get("revision_id") != revision_id
            or data.get("speaker_id") != speaker_id
        ):
            raise LookupError("excerpt reference is outside the requested scope")
        object_key = data.get("object_key")
        start_ms = data.get("start_ms")
        end_ms = data.get("end_ms")
        if not isinstance(object_key, str) or not isinstance(start_ms, int) or not isinstance(end_ms, int):
            raise LookupError("invalid excerpt reference")
        return object_key, start_ms, end_ms

    def play(
        self,
        reference: str,
        *,
        recording_id: str,
        revision_id: str,
        speaker_id: str,
        review_item,
    ) -> bytes:
        """Read the bound interval; read failures propagate without item mutation."""
        object_key, start_ms, end_ms = self.resolve(
            reference,
            recording_id=recording_id,
            revision_id=revision_id,
            speaker_id=speaker_id,
        )
        return self._read_interval(object_key, start_ms, end_ms)
