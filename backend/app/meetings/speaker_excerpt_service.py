"""Derive and resolve opaque, scope-bound speaker excerpt references."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class ExcerptCandidate(Protocol):
    """A diarization interval with its speaker assignment and VAD evidence."""

    start_ms: int
    end_ms: int
    vad_positive_windows: int
    vad_window_count: int
    assigned_speaker_id: str


@dataclass(frozen=True)
class ExcerptKeyring:
    """Versioned AES-256 keys for opaque excerpt references."""

    active_key_id: str
    keys: Mapping[str, bytes]

    def __post_init__(self) -> None:
        if not self.active_key_id or self.active_key_id not in self.keys:
            raise ValueError("active excerpt encryption key ID must exist in the keyring")
        copied = dict(self.keys)
        if any(
            not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", key_id)
            or not isinstance(key, bytes)
            or len(key) != 32
            for key_id, key in copied.items()
        ):
            raise ValueError("excerpt keyring entries must use safe IDs and 32-byte AES keys")
        object.__setattr__(self, "keys", MappingProxyType(copied))

    @classmethod
    def from_environment(cls) -> ExcerptKeyring:
        """Load keys injected by a deployment secret manager; never use a fallback."""
        encoded_keys = os.getenv("SPEAKER_EXCERPT_KEYRING")
        active_key_id = os.getenv("SPEAKER_EXCERPT_ACTIVE_KEY_ID")
        if not encoded_keys or not active_key_id:
            raise RuntimeError(
                "SPEAKER_EXCERPT_KEYRING and SPEAKER_EXCERPT_ACTIVE_KEY_ID must be configured"
            )

        keys: dict[str, bytes] = {}
        try:
            for entry in encoded_keys.split(","):
                key_id, separator, encoded_key = entry.partition(":")
                if not separator or not encoded_key:
                    raise ValueError("invalid keyring entry")
                key = base64.b64decode(
                    encoded_key + "=" * (-len(encoded_key) % 4),
                    altchars=b"-_",
                    validate=True,
                )
                if key_id in keys:
                    raise ValueError("duplicate key ID")
                keys[key_id] = key
        except (binascii.Error, ValueError) as error:
            raise RuntimeError("SPEAKER_EXCERPT_KEYRING is malformed") from error
        try:
            return cls(active_key_id=active_key_id, keys=keys)
        except ValueError as error:
            raise RuntimeError("SPEAKER_EXCERPT_KEYRING is invalid") from error


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

    def __init__(self, *, decode_interval, read_interval, keyring: ExcerptKeyring | None = None) -> None:
        self._decode_interval = decode_interval
        self._read_interval = read_interval
        self._keyring = keyring or ExcerptKeyring.from_environment()

    def derive(
        self,
        *,
        recording_id: str,
        revision_id: int,
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
            key_id = self._keyring.active_key_id
            associated_data = f"sauri-speaker-excerpt:v1:{key_id}".encode("ascii")
            ciphertext = AESGCM(self._keyring.keys[key_id]).encrypt(nonce, payload, associated_data)
            token = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii").rstrip("=")
            reference = f"v1.{key_id}.{token}"
            return SpeakerExcerpt(candidate.start_ms, candidate.end_ms, reference)

        raise ValueError("no validated speaker excerpt")

    def resolve(
        self,
        reference: str,
        *,
        recording_id: str,
        revision_id: int,
        speaker_id: str,
    ) -> tuple[str, int, int]:
        """Resolve only a well-formed reference for its exact source scope."""
        try:
            if not isinstance(reference, str):
                raise ValueError("invalid excerpt reference")
            version, key_id, encoded_token = reference.split(".", 2)
            if version != "v1" or key_id not in self._keyring.keys:
                raise ValueError("unknown excerpt key version")
            encoded = encoded_token.encode("ascii")
            token = base64.b64decode(
                encoded + b"=" * (-len(encoded) % 4),
                altchars=b"-_",
                validate=True,
            )
            if len(token) <= 12:
                raise ValueError("invalid excerpt reference")
            associated_data = f"sauri-speaker-excerpt:v1:{key_id}".encode("ascii")
            payload = AESGCM(self._keyring.keys[key_id]).decrypt(
                token[:12], token[12:], associated_data
            )
            data = json.loads(payload)
        except (binascii.Error, ValueError, UnicodeError, json.JSONDecodeError, InvalidTag) as error:
            raise LookupError("unknown excerpt reference") from error

        if not isinstance(data, dict):
            raise LookupError("invalid excerpt reference")
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

    def persist(self, excerpt: SpeakerExcerpt, *, review_item) -> None:
        """Store a validated reference only on the matching speaker review item."""
        review = review_item.review
        self.resolve(
            excerpt.reference,
            recording_id=review.meeting_id,
            revision_id=review.processing_revision,
            speaker_id=review_item.speaker_key,
        )
        review_item.excerpt_ref = excerpt.reference

    def play(
        self,
        *,
        recording_id: str,
        revision_id: int,
        review_item,
    ) -> bytes:
        """Read only the excerpt reference persisted on the authorized review item."""
        review = review_item.review
        if (
            review.meeting_id != recording_id
            or review.processing_revision != revision_id
            or not review_item.excerpt_ref
        ):
            raise LookupError("excerpt reference is outside the requested scope")
        object_key, start_ms, end_ms = self.resolve(
            review_item.excerpt_ref,
            recording_id=recording_id,
            revision_id=revision_id,
            speaker_id=review_item.speaker_key,
        )
        return self._read_interval(object_key, start_ms, end_ms)
