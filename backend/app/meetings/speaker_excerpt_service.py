"""Derive and resolve opaque, scope-bound speaker excerpt references."""

from __future__ import annotations

import asyncio
import base64
import binascii
import inspect
import json
import os
import re
import secrets
import signal
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol, cast

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.infra.object_store import ObjectStore


class ExcerptCandidate(Protocol):
    """A diarization interval with its speaker assignment and VAD evidence."""

    @property
    def start_ms(self) -> int: ...

    @property
    def end_ms(self) -> int: ...

    @property
    def vad_positive_windows(self) -> int: ...

    @property
    def vad_window_count(self) -> int: ...

    @property
    def assigned_speaker_id(self) -> str: ...


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


async def _spawn_decoder_process(
    *command: str, start_new_session: bool
) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=start_new_session,
    )


_PROCESS_PERMITS = asyncio.Semaphore(2)
_UNCONFIRMED_DECODERS = 0


class ManagedDecoderProcess:
    """Run a decoder in a dedicated process group and reap it on all paths."""

    def __init__(
        self,
        *,
        spawn_process: Callable[..., Awaitable[Any]] = _spawn_decoder_process,
        kill_process_group: Callable[[int, signal.Signals], None] = os.killpg,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._spawn_process = spawn_process
        self._kill_process_group = kill_process_group
        self._monotonic = monotonic

    async def run(
        self,
        command: tuple[str, ...],
        *,
        input_bytes: bytes,
        deadline_monotonic: float,
    ) -> bytes:
        """Return complete stdout only after the child exits successfully."""
        if not command or self._monotonic() >= deadline_monotonic:
            raise ValueError("speaker excerpt unavailable")
        remaining = deadline_monotonic - self._monotonic()
        if remaining <= 0:
            raise ValueError("speaker excerpt unavailable")
        try:
            process = await asyncio.wait_for(
                self._spawn_process(*command, start_new_session=True),
                timeout=remaining,
            )
        except TimeoutError:
            raise ValueError("speaker excerpt unavailable") from None
        communication = asyncio.create_task(process.communicate(input=input_bytes))
        try:
            remaining = deadline_monotonic - self._monotonic()
            if remaining <= 0:
                raise TimeoutError
            stdout, _stderr = await asyncio.wait_for(communication, timeout=remaining)
            return_code = await asyncio.wait_for(
                process.wait(), timeout=max(0.0, deadline_monotonic - self._monotonic())
            )
            if return_code != 0 or self._monotonic() > deadline_monotonic:
                raise ValueError("speaker excerpt unavailable")
            return cast(bytes, stdout)
        except BaseException as error:
            if getattr(process, "returncode", None) is None:
                global _UNCONFIRMED_DECODERS
                _UNCONFIRMED_DECODERS += 1
                communication.cancel()
                with suppress(BaseException):
                    await communication
                try:
                    self._kill_process_group(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError:
                    # A failed kill is not evidence of exit; retain unhealthy state.
                    pass
                reap_task = asyncio.create_task(process.wait())
                cancelled_again = False
                while not reap_task.done():
                    try:
                        await asyncio.shield(reap_task)
                    except asyncio.CancelledError:
                        cancelled_again = True
                    except BaseException:
                        break
                if (
                    reap_task.done()
                    and not reap_task.cancelled()
                    and reap_task.exception() is None
                ):
                    _UNCONFIRMED_DECODERS -= 1
                if cancelled_again:
                    raise asyncio.CancelledError from None
            if isinstance(error, asyncio.CancelledError):
                raise
            raise ValueError("speaker excerpt unavailable") from None


class SpeakerExcerptService:
    """Select validated intervals and encrypt their private source locator.

    The returned reference is intended to be persisted in the review item. Its
    authenticated encryption contains the server-side object locator and scope;
    callers must still authorize recording access before invoking ``play``.

    Interval callbacks build process arguments only. Source bytes are read through
    ``ObjectStore.get_bounded`` and every interval runs in ``ManagedDecoderProcess``.
    """

    MAX_SOURCE_BYTES = 20 * 1024 * 1024
    MAX_AUDIO_DURATION_MS = 30_000
    MAX_EXCERPT_DURATION_MS = 10_000
    MAX_OPERATION_SECONDS = 60.0

    def __init__(
        self,
        *,
        object_store: ObjectStore,
        decoder: ManagedDecoderProcess,
        decode_interval: Callable[..., Any],
        read_interval: Callable[..., Any],
        keyring: ExcerptKeyring | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._object_store = object_store
        self._decoder = decoder
        self._decode_interval = decode_interval
        self._read_interval = read_interval
        self._keyring = keyring or ExcerptKeyring.from_environment()
        self._monotonic = monotonic
        self._unhealthy = False

    async def _acquire(self) -> float:
        if self._unhealthy or _UNCONFIRMED_DECODERS > 0 or _PROCESS_PERMITS.locked():
            raise ValueError("speaker excerpt unavailable")
        await _PROCESS_PERMITS.acquire()
        return self._monotonic() + self.MAX_OPERATION_SECONDS

    async def _wait_for_worker(self, task: asyncio.Task[Any]) -> bool:
        """Wait for worker cleanup despite repeated request cancellation."""
        cancelled_again = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if not task.done():
                    cancelled_again = True
            except BaseException:
                break
        with suppress(BaseException):
            task.result()
        return cancelled_again

    async def _invoke(
        self, callback: Callable[..., Any], *args: Any, deadline_monotonic: float
    ) -> Any:
        remaining = deadline_monotonic - self._monotonic()
        if remaining <= 0:
            raise TimeoutError
        try:
            parameters = inspect.signature(callback).parameters.values()
            accepts_deadline = any(
                parameter.name == "deadline_monotonic"
                or parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters
            )
        except (TypeError, ValueError):
            accepts_deadline = False
        kwargs = {"deadline_monotonic": deadline_monotonic} if accepts_deadline else {}

        if inspect.iscoroutinefunction(callback):
            worker = asyncio.create_task(callback(*args, **kwargs))
            wait_for_completion = False
        else:
            worker = asyncio.create_task(asyncio.to_thread(callback, *args, **kwargs))
            wait_for_completion = True
        try:
            done, _pending = await asyncio.wait({worker}, timeout=remaining)
        except asyncio.CancelledError:
            self._unhealthy = True
            if not wait_for_completion:
                worker.cancel()
            await self._wait_for_worker(worker)
            self._unhealthy = False
            raise

        if not done:
            self._unhealthy = True
            if not wait_for_completion:
                worker.cancel()
            cancelled_again = await self._wait_for_worker(worker)
            self._unhealthy = False
            if cancelled_again:
                raise asyncio.CancelledError
            raise TimeoutError

        result = worker.result()
        if self._monotonic() >= deadline_monotonic:
            raise TimeoutError
        if inspect.isawaitable(result):
            nested = asyncio.ensure_future(result)
            nested_done, _pending = await asyncio.wait(
                {nested}, timeout=max(0.0, deadline_monotonic - self._monotonic())
            )
            if not nested_done:
                self._unhealthy = True
                nested.cancel()
                await self._wait_for_worker(nested)
                self._unhealthy = False
                raise TimeoutError
            return nested.result()
        return result

    async def _read_source(self, object_key: str, deadline_monotonic: float) -> bytes:
        source = await self._invoke(
            self._object_store.get_bounded,
            object_key,
            self.MAX_SOURCE_BYTES,
            deadline_monotonic=deadline_monotonic,
        )
        if not isinstance(source, bytes) or not source or len(source) > self.MAX_SOURCE_BYTES:
            raise ValueError("speaker excerpt unavailable")
        return source

    async def _decode_with_managed_process(
        self,
        command_builder: Callable[..., Any],
        object_key: str,
        start_ms: int,
        end_ms: int,
        source: bytes,
        deadline_monotonic: float,
    ) -> bytes:
        command = await self._invoke(
            command_builder,
            object_key,
            start_ms,
            end_ms,
            deadline_monotonic=deadline_monotonic,
        )
        if (
            not isinstance(command, Sequence)
            or isinstance(command, (str, bytes))
            or not command
            or any(not isinstance(part, str) or not part for part in command)
        ):
            raise ValueError("speaker excerpt unavailable")
        return await self._decoder.run(
            tuple(command),
            input_bytes=source,
            deadline_monotonic=deadline_monotonic,
        )

    async def derive(
        self,
        *,
        recording_id: str,
        revision_id: int,
        speaker_id: str,
        object_key: str,
        audio_duration_ms: int | None,
        candidates: Sequence[ExcerptCandidate],
    ) -> SpeakerExcerpt:
        """Return the highest-ranked candidate that passes all validations."""
        if (
            not isinstance(audio_duration_ms, int)
            or isinstance(audio_duration_ms, bool)
            or not 0 < audio_duration_ms <= self.MAX_AUDIO_DURATION_MS
            or not all((recording_id, revision_id, speaker_id, object_key))
        ):
            raise ValueError("speaker excerpt unavailable")

        deadline = await self._acquire()
        try:
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
            eligible = [
                candidate
                for candidate in ordered
                if candidate.assigned_speaker_id == speaker_id
                and candidate.start_ms >= 0
                and candidate.end_ms > candidate.start_ms
                and candidate.end_ms - candidate.start_ms <= self.MAX_EXCERPT_DURATION_MS
                and candidate.end_ms <= audio_duration_ms
                and candidate.vad_window_count > 0
                and candidate.vad_positive_windows > 0
                and candidate.vad_positive_windows <= candidate.vad_window_count
            ]
            if not eligible:
                raise ValueError("speaker excerpt unavailable")
            source = await self._read_source(object_key, deadline)
            for candidate in eligible:
                if self._monotonic() >= deadline:
                    raise TimeoutError("speaker excerpt unavailable")
                try:
                    decoded = await self._decode_with_managed_process(
                        self._decode_interval,
                        object_key,
                        candidate.start_ms,
                        candidate.end_ms,
                        source,
                        deadline,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    continue
                if not decoded:
                    continue
                if self._monotonic() >= deadline:
                    raise TimeoutError("speaker excerpt unavailable")
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
                ciphertext = AESGCM(self._keyring.keys[key_id]).encrypt(
                    nonce, payload, associated_data
                )
                token = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii").rstrip("=")
                reference = f"v1.{key_id}.{token}"
                return SpeakerExcerpt(candidate.start_ms, candidate.end_ms, reference)
            raise ValueError("speaker excerpt unavailable")
        except asyncio.CancelledError:
            raise
        except Exception:
            raise ValueError("speaker excerpt unavailable") from None
        finally:
            _PROCESS_PERMITS.release()

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

    def persist(self, excerpt: SpeakerExcerpt, *, review_item: Any) -> None:
        """Store a validated reference only on the matching speaker review item."""
        review = review_item.review
        self.resolve(
            excerpt.reference,
            recording_id=review.meeting_id,
            revision_id=review.processing_revision,
            speaker_id=review_item.speaker_key,
        )
        review_item.excerpt_ref = excerpt.reference

    async def play(
        self,
        *,
        recording_id: str,
        revision_id: int,
        review_item: Any,
    ) -> bytes:
        """Read only a complete excerpt persisted on the authorized review item."""
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
        if start_ms < 0 or end_ms <= start_ms or end_ms - start_ms > self.MAX_EXCERPT_DURATION_MS:
            raise ValueError("speaker excerpt unavailable")
        deadline = await self._acquire()
        try:
            source = await self._read_source(object_key, deadline)
            result = await self._decode_with_managed_process(
                self._read_interval,
                object_key,
                start_ms,
                end_ms,
                source,
                deadline,
            )
            if not isinstance(result, bytes) or not result or self._monotonic() >= deadline:
                raise ValueError("speaker excerpt unavailable")
            return result
        except asyncio.CancelledError:
            raise
        except Exception:
            raise ValueError("speaker excerpt unavailable") from None
        finally:
            _PROCESS_PERMITS.release()
