"""Derive and resolve opaque, scope-bound speaker excerpt references."""

from __future__ import annotations

import asyncio
import base64
import binascii
import inspect
import json
import math
import os
import re
import secrets
import signal
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol

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
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=start_new_session,
    )


_PROCESS_PERMITS = asyncio.Semaphore(2)
_UNCONFIRMED_DECODERS = 0
MAX_DECODER_OUTPUT_BYTES = 20 * 1024 * 1024
PROCESS_GROUP_CONFIRMATION_TIMEOUT_SECONDS = 1.0
PROCESS_GROUP_POLL_INTERVAL_SECONDS = 0.01


def _process_group_exists(process_group_id: int) -> bool | None:
    """Return False only when the OS confirms the process group is gone."""
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return None
    return True


class _OperationLease:
    """Own one process-wide permit until all associated work is confirmed done."""

    def __init__(self, deadline_monotonic: float) -> None:
        self.deadline_monotonic = deadline_monotonic
        self._deferred = False
        self._released = False

    def defer_release_until(self, reaper: asyncio.Task[bool]) -> None:
        self._deferred = True

        def release_when_reaped(task: asyncio.Task[bool]) -> None:
            if task.cancelled() or task.exception() is not None or not task.result():
                return
            if not self._released:
                self._released = True
                _PROCESS_PERMITS.release()

        reaper.add_done_callback(release_when_reaped)

    def release(self) -> None:
        if not self._deferred and not self._released:
            self._released = True
            _PROCESS_PERMITS.release()


class ManagedDecoderProcess:
    """Run a decoder in a dedicated process group and reap it on all paths."""

    def __init__(
        self,
        *,
        spawn_process: Callable[..., Awaitable[Any]] = _spawn_decoder_process,
        kill_process_group: Callable[[int, signal.Signals], None] = os.killpg,
        process_group_exists: Callable[[int], bool | None] = _process_group_exists,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._spawn_process = spawn_process
        self._kill_process_group = kill_process_group
        self._process_group_exists = process_group_exists
        self._monotonic = monotonic

    async def _confirm_process_group_termination(
        self,
        process_group_id: int,
        *,
        deadline_monotonic: float | None = None,
    ) -> bool:
        confirmation_deadline = (
            self._monotonic() + PROCESS_GROUP_CONFIRMATION_TIMEOUT_SECONDS
        )
        if deadline_monotonic is not None:
            confirmation_deadline = min(confirmation_deadline, deadline_monotonic)
        while True:
            try:
                group_exists = self._process_group_exists(process_group_id)
            except ProcessLookupError:
                return True
            except OSError:
                return False
            if group_exists is False:
                return True
            if group_exists is None:
                return False
            remaining = confirmation_deadline - self._monotonic()
            if remaining <= 0:
                return False
            await asyncio.sleep(min(PROCESS_GROUP_POLL_INTERVAL_SECONDS, remaining))

    async def _reap_in_background(
        self,
        process: Any,
        input_task: asyncio.Task[None],
        output_task: asyncio.Task[tuple[bytes, bool]],
        *,
        group_termination_requested: bool,
        group_termination_confirmed: bool,
    ) -> bool:
        """Retain worker health until group termination and child cleanup are confirmed."""
        global _UNCONFIRMED_DECODERS
        with suppress(asyncio.CancelledError):
            await input_task
        await output_task
        await process.wait()
        if not group_termination_confirmed and (
            not group_termination_requested
            or not await self._confirm_process_group_termination(process.pid)
        ):
            return False
        _UNCONFIRMED_DECODERS -= 1
        return True

    def _communicate_bounded(
        self, process: Any, input_bytes: bytes, max_output_bytes: int
    ) -> tuple[asyncio.Task[None], asyncio.Task[tuple[bytes, bool]]]:
        """Start stdin feeding and bounded stdout draining as separately reaped tasks."""

        async def feed_input() -> None:
            if process.stdin is None:
                raise ValueError("speaker excerpt unavailable")
            try:
                process.stdin.write(input_bytes)
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                return
            finally:
                with suppress(BrokenPipeError, ConnectionResetError):
                    process.stdin.close()
                    wait_closed = getattr(process.stdin, "wait_closed", None)
                    if wait_closed is not None:
                        await wait_closed()

        async def read_output() -> tuple[bytes, bool]:
            if process.stdout is None:
                raise ValueError("speaker excerpt unavailable")
            chunks: list[bytes] = []
            total = 0
            exceeded_limit = False
            while True:
                read_size = 64 * 1024
                if not exceeded_limit:
                    read_size = min(read_size, max_output_bytes + 1 - total)
                chunk = await process.stdout.read(read_size)
                if not isinstance(chunk, bytes):
                    raise ValueError("speaker excerpt unavailable")
                if not chunk:
                    break
                if exceeded_limit:
                    continue
                total += len(chunk)
                if total > max_output_bytes:
                    exceeded_limit = True
                    chunks.clear()
                else:
                    chunks.append(chunk)
            return b"".join(chunks), exceeded_limit

        return asyncio.create_task(feed_input()), asyncio.create_task(read_output())

    async def run(
        self,
        command: tuple[str, ...],
        *,
        input_bytes: bytes,
        deadline_monotonic: float,
        max_output_bytes: int = MAX_DECODER_OUTPUT_BYTES,
        on_reap: Callable[[asyncio.Task[bool]], None] | None = None,
    ) -> bytes:
        """Return complete stdout only after the child exits successfully."""
        if (
            not command
            or isinstance(max_output_bytes, bool)
            or not isinstance(max_output_bytes, int)
            or max_output_bytes <= 0
            or self._monotonic() >= deadline_monotonic
        ):
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
        input_task, output_task = self._communicate_bounded(
            process, input_bytes, max_output_bytes
        )
        try:
            remaining = deadline_monotonic - self._monotonic()
            if remaining <= 0:
                raise TimeoutError
            done, _pending = await asyncio.wait(
                {input_task, output_task},
                timeout=remaining,
                return_when=asyncio.FIRST_EXCEPTION,
            )
            for completed in done:
                if not completed.cancelled():
                    exception = completed.exception()
                    if exception is not None:
                        raise exception
            if input_task not in done or output_task not in done:
                raise TimeoutError
            input_task.result()
            stdout, exceeded_output_cap = output_task.result()
            if exceeded_output_cap:
                raise ValueError("speaker excerpt unavailable")
            return_code = await asyncio.wait_for(
                process.wait(), timeout=max(0.0, deadline_monotonic - self._monotonic())
            )
            if return_code != 0 or self._monotonic() > deadline_monotonic:
                raise ValueError("speaker excerpt unavailable")
            if not await self._confirm_process_group_termination(
                process.pid,
                deadline_monotonic=deadline_monotonic,
            ):
                raise ValueError("speaker excerpt unavailable")
            return stdout
        except BaseException as error:
            global _UNCONFIRMED_DECODERS
            _UNCONFIRMED_DECODERS += 1
            input_task.cancel()
            group_termination_requested = False
            group_termination_confirmed = False
            try:
                # The leader may exit while descendants remain. A successful signal
                # request is not proof that the entire process group has disappeared.
                self._kill_process_group(process.pid, signal.SIGKILL)
                group_termination_requested = True
            except ProcessLookupError:
                # A missing group is confirmation that there are no descendants.
                group_termination_confirmed = True
            except OSError:
                # A failed kill is not evidence of group exit; keep the lease held.
                pass
            reaper = asyncio.create_task(
                self._reap_in_background(
                    process,
                    input_task,
                    output_task,
                    group_termination_requested=group_termination_requested,
                    group_termination_confirmed=group_termination_confirmed,
                )
            )
            reaper.add_done_callback(self._observe_reaper)
            if on_reap is not None:
                on_reap(reaper)
            if not isinstance(error, asyncio.CancelledError):
                await asyncio.sleep(0)
            if isinstance(error, asyncio.CancelledError):
                raise
            raise ValueError("speaker excerpt unavailable") from None

    @staticmethod
    def _observe_reaper(task: asyncio.Task[bool]) -> None:
        if not task.cancelled():
            with suppress(BaseException):
                task.exception()


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
        probe_audio: Callable[..., Any],
        keyring: ExcerptKeyring | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._object_store = object_store
        self._decoder = decoder
        self._decode_interval = decode_interval
        self._read_interval = read_interval
        self._probe_audio = probe_audio
        self._keyring = keyring or ExcerptKeyring.from_environment()
        self._monotonic = monotonic
        self._unhealthy = False

    async def _acquire(self) -> _OperationLease:
        if self._unhealthy or _UNCONFIRMED_DECODERS > 0 or _PROCESS_PERMITS.locked():
            raise ValueError("speaker excerpt unavailable")
        await _PROCESS_PERMITS.acquire()
        return _OperationLease(self._monotonic() + self.MAX_OPERATION_SECONDS)

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

    async def _probe_duration(
        self, source: bytes, lease: _OperationLease
    ) -> int:
        """Probe actual source duration in a managed child before candidate decode."""
        command = await self._invoke(
            self._probe_audio,
            deadline_monotonic=lease.deadline_monotonic,
        )
        if (
            not isinstance(command, Sequence)
            or isinstance(command, (str, bytes))
            or not command
            or any(not isinstance(part, str) or not part for part in command)
        ):
            raise ValueError("speaker excerpt unavailable")
        result = await self._decoder.run(
            tuple(command),
            input_bytes=source,
            deadline_monotonic=lease.deadline_monotonic,
            max_output_bytes=128,
            on_reap=lease.defer_release_until,
        )
        try:
            duration_seconds = float(result.decode("ascii").strip())
        except (UnicodeDecodeError, ValueError):
            raise ValueError("speaker excerpt unavailable") from None
        if (
            not math.isfinite(duration_seconds)
            or duration_seconds <= 0
            or duration_seconds > self.MAX_AUDIO_DURATION_MS / 1000
        ):
            raise ValueError("speaker excerpt unavailable")
        return math.ceil(duration_seconds * 1000)

    async def _decode_with_managed_process(
        self,
        command_builder: Callable[..., Any],
        start_ms: int,
        end_ms: int,
        source: bytes,
        lease: _OperationLease,
    ) -> bytes:
        deadline_monotonic = lease.deadline_monotonic
        command = await self._invoke(
            command_builder,
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
            on_reap=lease.defer_release_until,
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

        lease = await self._acquire()
        deadline = lease.deadline_monotonic
        try:
            source = await self._read_source(object_key, deadline)
            actual_duration_ms = await self._probe_duration(source, lease)
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
                and candidate.end_ms <= actual_duration_ms
                and candidate.vad_window_count > 0
                and candidate.vad_positive_windows > 0
                and candidate.vad_positive_windows <= candidate.vad_window_count
            ]
            if not eligible:
                raise ValueError("speaker excerpt unavailable")
            for candidate in eligible:
                if self._monotonic() >= deadline:
                    raise TimeoutError("speaker excerpt unavailable")
                try:
                    decoded = await self._decode_with_managed_process(
                        self._decode_interval,
                        candidate.start_ms,
                        candidate.end_ms,
                        source,
                        lease,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    if _UNCONFIRMED_DECODERS > 0:
                        raise ValueError("speaker excerpt unavailable") from None
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
            lease.release()

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
        lease = await self._acquire()
        deadline = lease.deadline_monotonic
        try:
            source = await self._read_source(object_key, deadline)
            actual_duration_ms = await self._probe_duration(source, lease)
            if end_ms > actual_duration_ms:
                raise ValueError("speaker excerpt unavailable")
            result = await self._decode_with_managed_process(
                self._read_interval,
                start_ms,
                end_ms,
                source,
                lease,
            )
            if not isinstance(result, bytes) or not result or self._monotonic() >= deadline:
                raise ValueError("speaker excerpt unavailable")
            return result
        except asyncio.CancelledError:
            raise
        except Exception:
            raise ValueError("speaker excerpt unavailable") from None
        finally:
            lease.release()
