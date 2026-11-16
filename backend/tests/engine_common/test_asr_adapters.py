"""External transcription adapters against fake providers on 127.0.0.1 (no real provider, no real audio).

The fakes mimic the documented answer shapes (Groq/OpenAI ``verbose_json``, AssemblyAI upload, transcript and
delete, Deepgram ``/v1/listen``). The audio is placeholder bytes: no fake decodes it. Spanish support and the
real size limits are NO VERIFICADO until U10; nothing here proves them.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import sys
import time
import traceback
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sauri_engine_common.external import asr_assemblyai, asr_deepgram, asr_openai_audio
from sauri_engine_common.external.asr_common import (
    AdapterCancelled,
    AsrResult,
    AsrWord,
    HttpTransport,
    ProviderLimits,
    merge_parts,
)
from sauri_engine_common.external.errors import ProviderError, classify
from sauri_engine_common.route import Route, RouteTimeouts
from sauri_engine_common.secrets import SecretRecord

KEY = "sk-test-KEY-0123456789abcdef"
PHRASE = "frase confidencial del proveedor"
SECRET = SecretRecord(key=KEY, origin="http://127.0.0.1")


# --- fake provider -------------------------------------------------------------------------------------


@dataclass
class Seen:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes

    @property
    def query(self) -> dict[str, list[str]]:
        return parse_qs(urlsplit(self.path).query)


@dataclass
class Reply:
    status: int = 200
    body: Any = None
    raw: bytes | None = None
    headers: dict[str, str] = field(default_factory=dict)
    delay_s: float = 0.0
    hang: bool = False  # keep the stream open until the client disconnects


_REASONS = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 413: "Payload Too Large", 429: "Too Many Requests"}


class FakeProvider:
    """asyncio HTTP/1.1 server; routes map ``"METHOD /path"`` to a Reply, a callable or a reply sequence."""

    def __init__(self) -> None:
        self.routes: dict[str, Reply | Callable[[Seen], Reply] | list[Reply]] = {}
        self.seen: list[Seen] = []
        self.open = 0  # connections the provider still considers alive
        self._server: asyncio.Server | None = None
        self.port = 0

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._connection, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def calls(self, method: str, prefix: str) -> list[Seen]:
        return [s for s in self.seen if s.method == method and s.path.startswith(prefix)]

    async def wait_open(self, count: int, timeout_s: float = 2.0) -> None:
        deadline = time.monotonic() + timeout_s
        while self.open != count:
            assert time.monotonic() < deadline, f"open streams stayed at {self.open}"
            await asyncio.sleep(0.01)

    def _reply_for(self, request: Seen) -> Reply:
        route = self.routes.get(f"{request.method} {request.path.split('?')[0]}")
        if route is None:
            return Reply(404, {"error": "not_found"})
        if callable(route):
            return route(request)
        if isinstance(route, list):
            return route.pop(0) if len(route) > 1 else route[0]
        return route

    async def _connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.open += 1
        try:
            head = (await reader.readuntil(b"\r\n\r\n")).decode("latin-1").split("\r\n")
            method, path, _version = head[0].split(" ", 2)
            headers = {k.lower(): v.strip() for k, v in (line.split(":", 1) for line in head[1:] if ":" in line)}
            body = await reader.readexactly(int(headers.get("content-length", "0")))
            request = Seen(method, path, headers, body)
            self.seen.append(request)
            reply = self._reply_for(request)
            if reply.hang:
                await reader.read()  # returns at EOF: the client closed the connection
                return
            if reply.delay_s:
                await asyncio.sleep(reply.delay_s)
            payload = reply.raw if reply.raw is not None else json.dumps(reply.body).encode()
            lines = [
                f"HTTP/1.1 {reply.status} {_REASONS.get(reply.status, 'Status')}",
                "content-type: application/json",
                f"content-length: {len(payload)}",
                "connection: close",
                *(f"{name}: {value}" for name, value in reply.headers.items()),
            ]
            writer.write(("\r\n".join(lines) + "\r\n\r\n").encode() + payload)
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            self.open -= 1
            writer.close()


@dataclass(frozen=True)
class Response:
    status: int
    retry_after: str | None
    body: bytes


class LoopbackHttp:
    """Test transport with the call shape of ``SafeHttp.request`` (no address policy: loopback only)."""

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
        allow_local: bool,
        total_timeout_s: float,
        connect_timeout_s: float = 3.0,
    ) -> Response:
        assert allow_local and urlsplit(url).hostname == "127.0.0.1"
        timeout = httpx.Timeout(total_timeout_s, connect=connect_timeout_s)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, url, headers=headers, content=body)
        except httpx.HTTPError as exc:
            raise classify(None, exc=exc) from None
        return Response(response.status_code, response.headers.get("retry-after"), response.content)


@pytest.fixture
async def fake() -> AsyncIterator[FakeProvider]:
    provider = FakeProvider()
    await provider.start()
    yield provider
    await provider.stop()


@pytest.fixture
def http() -> HttpTransport:
    return LoopbackHttp()


@pytest.fixture
def audio(tmp_path: Path) -> Path:
    path = tmp_path / "part.ogg"
    path.write_bytes(b"OggS" + b"\x00" * 2048)
    return path


def make_route(
    fake: FakeProvider, transport: str, *, model: str = "model-x", base: str = "", total_s: float = 5.0
) -> Route:
    return Route(
        version=1,
        capability="transcription",
        kind="test",
        transport=transport,  # type: ignore[arg-type]
        base_url=fake.url + base,
        model=model,
        secret_ref=None,
        consent_version=1,
        timeouts=RouteTimeouts(connect_s=2.0, first_byte_s=2.0, idle_s=2.0, total_s=total_s),
    )


def fields_of(multipart: bytes) -> list[tuple[str, str]]:
    """Name/value pairs of the text fields of a multipart body (the file part is skipped)."""
    out: list[tuple[str, str]] = []
    for part in multipart.split(b"--sauri-")[1:]:
        head, _, rest = part.partition(b"\r\n\r\n")
        if b'name="file"' in head or b"Content-Disposition" not in head:
            continue
        name = head.split(b'name="', 1)[1].split(b'"', 1)[0].decode()
        out.append((name, rest.rsplit(b"\r\n", 1)[0].decode()))
    return out


# --- openai-audio ------------------------------------------------------------------------------------

VERBOSE: dict[str, Any] = {
    "task": "transcribe",
    "language": "spanish",
    "duration": 4.5,
    "text": f"hola {PHRASE}",
    "segments": [
        {"id": 0, "start": 0.0, "end": 2.0, "text": "hola"},
        {"id": 1, "start": 2.0, "end": 4.4, "text": PHRASE},
    ],
    "words": [
        {"word": "hola", "start": 0.2, "end": 0.6},
        {"word": "frase", "start": 2.1, "end": 2.5},
        {"word": "confidencial", "start": 2.6, "end": 3.4},
    ],
}
GROQ_PATH = "/openai/v1/audio/transcriptions"


async def openai_call(fake: FakeProvider, http: HttpTransport, audio: Path, **kwargs: Any) -> AsrResult:
    route = make_route(fake, "openai-audio", base="/openai/v1", model=kwargs.pop("model", "whisper-large-v3-turbo"),
                       total_s=kwargs.pop("total_s", 5.0))  # fmt: skip
    cancel = kwargs.pop("cancel", None) or asyncio.Event()
    return await asr_openai_audio.transcribe(
        http, audio, language=kwargs.pop("language", "es"), route=route, secret=SECRET, cancel=cancel,
        allow_local=True, **kwargs,
    )  # fmt: skip


async def test_openai_audio_sends_documented_request_and_normalizes_words(
    fake: FakeProvider, http: HttpTransport, audio: Path
) -> None:
    fake.routes[f"POST {GROQ_PATH}"] = Reply(body=VERBOSE)
    result = await openai_call(fake, http, audio, audio_ms=4500)
    (request,) = fake.seen
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert fields_of(request.body) == [
        ("model", "whisper-large-v3-turbo"),
        ("response_format", "verbose_json"),
        ("timestamp_granularities[]", "word"),
        ("timestamp_granularities[]", "segment"),
        ("language", "es"),
    ]
    assert b'filename="audio.ogg"' in request.body and b"Content-Type: audio/ogg" in request.body
    assert [(w.text, w.start_ms, w.end_ms) for w in result.words] == [
        ("hola", 200, 600), ("frase", 2100, 2500), ("confidencial", 2600, 3400),
    ]  # fmt: skip
    assert result.language == "es" and len(result.segments) == 2 and result.audio_ms == 4500


async def test_openai_audio_auto_language_omits_the_field_and_maps_the_detected_name(
    fake: FakeProvider, http: HttpTransport, audio: Path
) -> None:
    fake.routes[f"POST {GROQ_PATH}"] = Reply(body={**VERBOSE, "language": "portuguese"})
    result = await openai_call(fake, http, audio, language="auto")
    assert "language" not in dict(fields_of(fake.seen[0].body))
    assert result.language == "pt"


async def test_openai_audio_text_without_words_is_no_word_timestamps(
    fake: FakeProvider, http: HttpTransport, audio: Path
) -> None:
    fake.routes[f"POST {GROQ_PATH}"] = Reply(body={k: v for k, v in VERBOSE.items() if k != "words"})
    with pytest.raises(ProviderError) as caught:
        await openai_call(fake, http, audio)
    assert caught.value.code == "no_word_timestamps" and not caught.value.retryable


async def test_openai_audio_segment_with_text_but_no_nearby_word_is_rejected(
    fake: FakeProvider, http: HttpTransport, audio: Path
) -> None:
    gap = {**VERBOSE, "words": VERBOSE["words"][:1]}  # the second segment (2.0-4.4 s) has no word
    fake.routes[f"POST {GROQ_PATH}"] = Reply(body=gap)
    with pytest.raises(ProviderError) as caught:
        await openai_call(fake, http, audio)
    assert caught.value.code == "no_word_timestamps"


async def test_openai_audio_silence_is_an_empty_result_not_an_error(
    fake: FakeProvider, http: HttpTransport, audio: Path
) -> None:
    fake.routes[f"POST {GROQ_PATH}"] = Reply(
        body={"text": "", "language": "spanish", "duration": 3.0, "words": [], "segments": []}
    )
    result = await openai_call(fake, http, audio)
    assert result.words == () and result.language == "es"


@pytest.mark.parametrize(
    ("reply", "code", "retryable", "retry_after"),
    [
        (
            Reply(429, {"error": {"code": "rate_limit_exceeded"}}, headers={"Retry-After": "7"}),
            "provider_rate_limited",
            True,
            7,
        ),
        (Reply(429, {"error": {"type": "insufficient_quota"}}), "provider_quota", True, None),
        (Reply(401, {"error": {"message": "bad key"}}), "provider_auth", False, None),
        (Reply(413, {}), "audio_too_large", False, None),
        (Reply(500, {"error": "boom"}), "provider_unavailable", True, None),
        (Reply(503, {}, headers={"Retry-After": "2"}), "provider_unavailable", True, 2),
        (Reply(400, {"error": {"code": "invalid_request"}}), "provider_bad_request", False, None),
        (Reply(200, raw=b"<html>not json</html>"), "provider_invalid_output", False, None),
    ],
)
async def test_openai_audio_classifies_provider_answers(
    fake: FakeProvider,
    http: HttpTransport,
    audio: Path,
    reply: Reply,
    code: str,
    retryable: bool,
    retry_after: int | None,
) -> None:
    fake.routes[f"POST {GROQ_PATH}"] = reply
    with pytest.raises(ProviderError) as caught:
        await openai_call(fake, http, audio)
    assert (caught.value.code, caught.value.retryable, caught.value.retry_after_s) == (code, retryable, retry_after)


async def test_openai_audio_times_out_with_the_route_timeout(
    fake: FakeProvider, http: HttpTransport, audio: Path
) -> None:
    fake.routes[f"POST {GROQ_PATH}"] = Reply(body=VERBOSE, delay_s=1.5)
    started = time.monotonic()
    with pytest.raises(ProviderError) as caught:
        await openai_call(fake, http, audio, total_s=0.2)
    assert caught.value.code == "provider_timeout" and caught.value.retryable
    assert time.monotonic() - started < 1.2


async def test_openai_audio_refuses_an_oversized_part_without_contacting_the_provider(
    fake: FakeProvider, http: HttpTransport, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(asr_openai_audio, "LIMITS", ProviderLimits(max_upload_bytes=1000, max_audio_s=None))
    big = tmp_path / "big.ogg"
    big.write_bytes(b"x" * 1001)
    with pytest.raises(ProviderError) as caught:
        await openai_call(fake, http, big)
    assert caught.value.code == "audio_too_large" and fake.seen == []


async def test_openai_audio_rejects_a_malformed_model_and_language_before_any_call(
    fake: FakeProvider, http: HttpTransport, audio: Path
) -> None:
    for kwargs in ({"model": 'x"\r\nname="y'}, {"language": "spanish"}):
        with pytest.raises(ProviderError) as caught:
            await openai_call(fake, http, audio, **kwargs)
        assert caught.value.code == "provider_bad_request"
    assert fake.seen == []


async def test_openai_audio_cancel_closes_the_stream_to_the_provider(
    fake: FakeProvider, http: HttpTransport, audio: Path
) -> None:
    fake.routes[f"POST {GROQ_PATH}"] = Reply(hang=True)
    cancel = asyncio.Event()
    task = asyncio.create_task(openai_call(fake, http, audio, cancel=cancel))
    await fake.wait_open(1)
    cancel.set()
    with pytest.raises(AdapterCancelled):
        await task
    await fake.wait_open(0, timeout_s=2.0)


async def test_openai_audio_task_cancellation_closes_the_stream_too(
    fake: FakeProvider, http: HttpTransport, audio: Path
) -> None:
    fake.routes[f"POST {GROQ_PATH}"] = Reply(hang=True)
    task = asyncio.create_task(openai_call(fake, http, audio))
    await fake.wait_open(1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await fake.wait_open(0, timeout_s=2.0)


async def test_openai_audio_already_cancelled_sends_nothing(
    fake: FakeProvider, http: HttpTransport, audio: Path
) -> None:
    cancel = asyncio.Event()
    cancel.set()
    with pytest.raises(AdapterCancelled):
        await openai_call(fake, http, audio, cancel=cancel)
    assert fake.seen == []


# --- assemblyai --------------------------------------------------------------------------------------

AAI_DONE = {
    "id": "tr-1",
    "status": "completed",
    "language_code": "es",
    "audio_duration": 5,
    "text": f"hola {PHRASE}",
    "words": [
        {"text": "hola", "start": 200, "end": 640, "confidence": 0.98},
        {"text": "frase", "start": 2100, "end": 2500, "confidence": 0.91},
        {"text": "confidencial", "start": 2600, "end": 3400, "confidence": 0.9},
    ],
}


@pytest.fixture
def fast_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asr_assemblyai, "POLL_INITIAL_S", 0.01)
    monkeypatch.setattr(asr_assemblyai, "POLL_MAX_S", 0.02)


class AssemblyFake:
    """Provider state for the fake: transcript statuses served in order, and what was deleted."""

    def __init__(self, fake: FakeProvider, statuses: list[Reply]) -> None:
        self.deleted: list[str] = []
        fake.routes["POST /v2/upload"] = Reply(body={"upload_url": "https://cdn.example.test/upload/abc"})
        fake.routes["POST /v2/transcript"] = Reply(body={"id": "tr-1", "status": "queued"})
        fake.routes["GET /v2/transcript/tr-1"] = statuses
        fake.routes["DELETE /v2/transcript/tr-1"] = self._delete

    def _delete(self, _request: Seen) -> Reply:
        self.deleted.append("tr-1")
        return Reply(body={"id": "tr-1", "status": "completed", "text": None, "words": None})


async def assembly_call(fake: FakeProvider, http: HttpTransport, audio: Path, **kwargs: Any) -> AsrResult:
    route = make_route(fake, "assemblyai", model=kwargs.pop("model", "universal-2"), total_s=kwargs.pop("total_s", 5.0))
    cancel = kwargs.pop("cancel", None) or asyncio.Event()
    return await asr_assemblyai.transcribe(
        http, audio, language=kwargs.pop("language", "es"), route=route, secret=SECRET, cancel=cancel,
        allow_local=True, **kwargs,
    )  # fmt: skip


async def test_assemblyai_uploads_creates_polls_and_deletes_the_remote_transcript(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    state = AssemblyFake(fake, [Reply(body={"id": "tr-1", "status": "queued"}),
                                Reply(body={"id": "tr-1", "status": "processing"}), Reply(body=AAI_DONE)])  # fmt: skip
    result = await assembly_call(fake, http, audio, audio_ms=5000)
    assert [(s.method, s.path) for s in fake.seen][:3] == [
        ("POST", "/v2/upload"), ("POST", "/v2/transcript"), ("GET", "/v2/transcript/tr-1"),
    ]  # fmt: skip
    upload, create = fake.seen[0], fake.seen[1]
    assert upload.headers["authorization"] == KEY  # raw key, no scheme
    assert upload.headers["content-type"] == "application/octet-stream" and upload.body.startswith(b"OggS")
    assert json.loads(create.body) == {
        "speech_models": ["universal-2"], "language_code": "es", "audio_url": "https://cdn.example.test/upload/abc",
    }  # fmt: skip
    assert [(w.text, w.start_ms, w.end_ms, w.probability) for w in result.words] == [
        ("hola", 200, 640, 0.98), ("frase", 2100, 2500, 0.91), ("confidencial", 2600, 3400, 0.9),
    ]  # fmt: skip
    assert result.language == "es" and result.diagnostics == {"remote_deleted": True}
    assert state.deleted == ["tr-1"] and fake.calls("DELETE", "/v2/transcript/tr-1")[0].headers["authorization"] == KEY
    await fake.wait_open(0)


async def test_assemblyai_auto_language_uses_detection(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    AssemblyFake(fake, [Reply(body={**AAI_DONE, "language_code": "en_us"})])
    result = await assembly_call(fake, http, audio, language="auto")
    assert json.loads(fake.seen[1].body)["language_detection"] is True and "language_code" not in json.loads(
        fake.seen[1].body
    )
    assert result.language == "en"


async def test_assemblyai_text_without_words_fails_and_still_deletes(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    state = AssemblyFake(fake, [Reply(body={**AAI_DONE, "words": None})])
    with pytest.raises(ProviderError) as caught:
        await assembly_call(fake, http, audio)
    assert caught.value.code == "no_word_timestamps" and state.deleted == ["tr-1"]


async def test_assemblyai_job_error_is_classified_and_deleted(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    state = AssemblyFake(fake, [Reply(body={"id": "tr-1", "status": "error", "error": f"Audio roto: {PHRASE}"})])
    with pytest.raises(ProviderError) as caught:
        await assembly_call(fake, http, audio)
    assert (caught.value.code, caught.value.reason) == ("provider_bad_request", "job_failed")
    assert state.deleted == ["tr-1"] and PHRASE not in repr(caught.value)


async def test_assemblyai_server_side_job_failure_is_retryable(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    AssemblyFake(
        fake, [Reply(body={"id": "tr-1", "status": "error", "error": "Server error, developers have been alerted"})]
    )
    with pytest.raises(ProviderError) as caught:
        await assembly_call(fake, http, audio)
    assert caught.value.code == "provider_unavailable" and caught.value.retryable


async def test_assemblyai_polling_cap_stops_waits_and_deletes_the_job(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    state = AssemblyFake(fake, [Reply(body={"id": "tr-1", "status": "processing"})])
    started = time.monotonic()
    with pytest.raises(ProviderError) as caught:
        await assembly_call(fake, http, audio, deadline_s=0.3)
    assert caught.value.code == "provider_timeout" and caught.value.retryable
    assert time.monotonic() - started < 2.0
    assert state.deleted == ["tr-1"] and len(fake.calls("GET", "/v2/transcript/tr-1")) >= 2


async def test_assemblyai_default_cap_is_the_engine_call_timeout() -> None:
    assert asr_assemblyai.DEFAULT_DEADLINE_S == 1200.0


async def test_assemblyai_polling_tolerates_a_transient_error(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    AssemblyFake(fake, [Reply(503, {}), Reply(body=AAI_DONE)])
    result = await assembly_call(fake, http, audio)
    assert len(result.words) == 3 and len(fake.calls("GET", "/v2/transcript/tr-1")) == 2


async def test_assemblyai_polling_gives_up_after_repeated_errors_and_deletes(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    state = AssemblyFake(fake, [Reply(503, {})])
    with pytest.raises(ProviderError) as caught:
        await assembly_call(fake, http, audio)
    assert caught.value.code == "provider_unavailable" and state.deleted == ["tr-1"]
    assert len(fake.calls("GET", "/v2/transcript/tr-1")) == asr_assemblyai.MAX_POLL_ERRORS + 1


async def test_assemblyai_rate_limit_and_auth_on_create(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    AssemblyFake(fake, [Reply(body=AAI_DONE)])
    fake.routes["POST /v2/transcript"] = Reply(429, {"error": "slow down"}, headers={"Retry-After": "11"})
    with pytest.raises(ProviderError) as caught:
        await assembly_call(fake, http, audio)
    assert (caught.value.code, caught.value.retry_after_s) == ("provider_rate_limited", 11)
    assert fake.calls("DELETE", "/v2/") == []  # no transcript id yet: nothing to delete
    fake.routes["POST /v2/upload"] = Reply(401, {"error": "Invalid API key"})
    with pytest.raises(ProviderError) as auth:
        await assembly_call(fake, http, audio)
    assert auth.value.code == "provider_auth"


async def test_assemblyai_upload_timeout(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    AssemblyFake(fake, [Reply(body=AAI_DONE)])
    fake.routes["POST /v2/upload"] = Reply(body={"upload_url": "https://x.test/u"}, delay_s=1.5)
    with pytest.raises(ProviderError) as caught:
        await assembly_call(fake, http, audio, total_s=0.2)
    assert caught.value.code == "provider_timeout"


async def test_assemblyai_cancel_while_polling_deletes_the_remote_job(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    state = AssemblyFake(fake, [Reply(body={"id": "tr-1", "status": "processing"})])
    cancel = asyncio.Event()
    task = asyncio.create_task(assembly_call(fake, http, audio, cancel=cancel))
    deadline = time.monotonic() + 2
    while not fake.calls("GET", "/v2/transcript/tr-1"):
        assert time.monotonic() < deadline
        await asyncio.sleep(0.01)
    cancel.set()
    with pytest.raises(AdapterCancelled):
        await task
    assert state.deleted == ["tr-1"]
    await fake.wait_open(0, timeout_s=2.0)


async def test_assemblyai_task_cancellation_while_polling_still_deletes(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    state = AssemblyFake(fake, [Reply(body={"id": "tr-1", "status": "processing"})])
    task = asyncio.create_task(assembly_call(fake, http, audio))
    deadline = time.monotonic() + 2
    while not fake.calls("GET", "/v2/transcript/tr-1"):
        assert time.monotonic() < deadline
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert state.deleted == ["tr-1"]
    await fake.wait_open(0, timeout_s=2.0)


async def test_assemblyai_cancel_during_upload_leaves_no_open_stream_and_creates_nothing(
    fake: FakeProvider, http: HttpTransport, audio: Path
) -> None:
    fake.routes["POST /v2/upload"] = Reply(hang=True)
    cancel = asyncio.Event()
    task = asyncio.create_task(assembly_call(fake, http, audio, cancel=cancel))
    await fake.wait_open(1)
    cancel.set()
    with pytest.raises(AdapterCancelled):
        await task
    await fake.wait_open(0, timeout_s=2.0)
    assert fake.calls("POST", "/v2/transcript") == []


async def test_assemblyai_failed_deletion_does_not_hide_the_result(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None, caplog: pytest.LogCaptureFixture
) -> None:
    AssemblyFake(fake, [Reply(body=AAI_DONE)])
    fake.routes["DELETE /v2/transcript/tr-1"] = Reply(500, {"error": f"{KEY} {PHRASE}"})
    with caplog.at_level(logging.DEBUG):
        result = await assembly_call(fake, http, audio)
    assert len(result.words) == 3 and result.diagnostics == {"remote_deleted": False}
    assert any("deletion failed" in record.getMessage() for record in caplog.records)


async def test_assemblyai_rejects_an_unsafe_transcript_id(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    AssemblyFake(fake, [Reply(body=AAI_DONE)])
    fake.routes["POST /v2/transcript"] = Reply(body={"id": "../../v2/upload", "status": "queued"})
    with pytest.raises(ProviderError) as caught:
        await assembly_call(fake, http, audio)
    assert caught.value.code == "provider_invalid_output" and fake.calls("DELETE", "/") == []


# --- deepgram ----------------------------------------------------------------------------------------

DG_DONE = {
    "metadata": {"request_id": "r-1", "duration": 4.5, "channels": 1},
    "results": {
        "channels": [
            {
                "detected_language": "es",
                "alternatives": [
                    {
                        "transcript": f"Hola. {PHRASE}",
                        "confidence": 0.99,
                        "words": [
                            {"word": "hola", "punctuated_word": "Hola.", "start": 0.2, "end": 0.64, "confidence": 0.97},
                            {"word": "frase", "start": 2.1, "end": 2.5, "confidence": 0.9},
                            {"word": "confidencial", "start": 2.6, "end": 3.4, "confidence": 0.88},
                        ],
                    }
                ],
            }
        ],
        "utterances": [
            {"start": 0.2, "end": 0.64, "transcript": "Hola."},
            {"start": 2.1, "end": 3.4, "transcript": PHRASE},
        ],
    },
}


async def deepgram_call(fake: FakeProvider, http: HttpTransport, audio: Path, **kwargs: Any) -> AsrResult:
    route = make_route(fake, "deepgram", model=kwargs.pop("model", "nova-3"), total_s=kwargs.pop("total_s", 5.0))
    cancel = kwargs.pop("cancel", None) or asyncio.Event()
    return await asr_deepgram.transcribe(
        http, audio, language=kwargs.pop("language", "es"), route=route, secret=SECRET, cancel=cancel,
        allow_local=True, **kwargs,
    )  # fmt: skip


async def test_deepgram_sends_raw_audio_with_documented_query_and_normalizes_words(
    fake: FakeProvider, http: HttpTransport, audio: Path
) -> None:
    fake.routes["POST /v1/listen"] = Reply(body=DG_DONE)
    result = await deepgram_call(fake, http, audio, audio_ms=4500)
    (request,) = fake.seen
    assert request.headers["authorization"] == f"Token {KEY}" and request.headers["content-type"] == "audio/ogg"
    assert request.body == audio.read_bytes()
    assert request.query == {
        "model": ["nova-3"],
        "language": ["es"],
        "smart_format": ["true"],
        "punctuate": ["true"],
        "utterances": ["true"],
    }
    assert [(w.text, w.start_ms, w.end_ms, w.probability) for w in result.words] == [
        ("Hola.", 200, 640, 0.97), ("frase", 2100, 2500, 0.9), ("confidencial", 2600, 3400, 0.88),
    ]  # fmt: skip
    assert result.language == "es" and len(result.segments) == 2


async def test_deepgram_auto_language_uses_detection(fake: FakeProvider, http: HttpTransport, audio: Path) -> None:
    fake.routes["POST /v1/listen"] = Reply(body=DG_DONE)
    result = await deepgram_call(fake, http, audio, language="auto")
    query = fake.seen[0].query
    assert query["detect_language"] == ["true"] and "language" not in query
    assert result.language == "es"


async def test_deepgram_transcript_without_words_is_no_word_timestamps(
    fake: FakeProvider, http: HttpTransport, audio: Path
) -> None:
    bare = json.loads(json.dumps(DG_DONE))
    bare["results"]["channels"][0]["alternatives"][0]["words"] = []
    fake.routes["POST /v1/listen"] = Reply(body=bare)
    with pytest.raises(ProviderError) as caught:
        await deepgram_call(fake, http, audio)
    assert caught.value.code == "no_word_timestamps"


async def test_deepgram_silence_is_an_empty_result(fake: FakeProvider, http: HttpTransport, audio: Path) -> None:
    silent = {
        "metadata": {"duration": 3.0},
        "results": {"channels": [{"alternatives": [{"transcript": "", "words": []}]}]},
    }
    fake.routes["POST /v1/listen"] = Reply(body=silent)
    assert (await deepgram_call(fake, http, audio)).words == ()


async def test_deepgram_unexpected_shape_is_invalid_output(
    fake: FakeProvider, http: HttpTransport, audio: Path
) -> None:
    fake.routes["POST /v1/listen"] = Reply(body={"results": {}})
    with pytest.raises(ProviderError) as caught:
        await deepgram_call(fake, http, audio)
    assert caught.value.code == "provider_invalid_output"


@pytest.mark.parametrize(
    ("reply", "code", "retry_after"),
    [
        (Reply(429, {"err_code": "TOO_MANY"}, headers={"Retry-After": "3"}), "provider_rate_limited", 3),
        (Reply(401, {"err_code": "INVALID_AUTH"}), "provider_auth", None),
        (Reply(402, {}), "provider_quota", None),
        (Reply(504, {}), "provider_timeout", None),
        (Reply(502, {}), "provider_unavailable", None),
        (Reply(400, {"err_code": "Bad Request"}), "provider_bad_request", None),
    ],
)
async def test_deepgram_classifies_provider_answers(
    fake: FakeProvider, http: HttpTransport, audio: Path, reply: Reply, code: str, retry_after: int | None
) -> None:
    fake.routes["POST /v1/listen"] = reply
    with pytest.raises(ProviderError) as caught:
        await deepgram_call(fake, http, audio)
    assert (caught.value.code, caught.value.retry_after_s) == (code, retry_after)


async def test_deepgram_times_out_and_cancels(fake: FakeProvider, http: HttpTransport, audio: Path) -> None:
    fake.routes["POST /v1/listen"] = Reply(body=DG_DONE, delay_s=1.5)
    with pytest.raises(ProviderError) as caught:
        await deepgram_call(fake, http, audio, total_s=0.2)
    assert caught.value.code == "provider_timeout"
    fake.routes["POST /v1/listen"] = Reply(hang=True)
    cancel = asyncio.Event()
    task = asyncio.create_task(deepgram_call(fake, http, audio, cancel=cancel))
    await fake.wait_open(1)
    cancel.set()
    with pytest.raises(AdapterCancelled):
        await task
    await fake.wait_open(0, timeout_s=2.0)


# --- Property 7: words are never invented ------------------------------------------------------------

seconds = st.floats(min_value=-5, max_value=30, allow_nan=False, allow_infinity=False)


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(
    raw=st.lists(st.tuples(st.sampled_from(["a", "b c", " ", "", "ñ"]), seconds, seconds), min_size=0, max_size=12),
    duration=st.floats(min_value=0.5, max_value=20, allow_nan=False, allow_infinity=False),
)
def test_property_7_emitted_words_are_ordered_pairs_inside_the_audio(
    raw: list[tuple[str, float, float]], duration: float
) -> None:
    doc: dict[str, Any] = {
        "text": " ".join(w for w, _s, _e in raw),
        "duration": duration,
        "language": "spanish",
        "words": [{"word": w, "start": s, "end": e} for w, s, e in raw],
    }
    limit = round(duration * 1000)
    try:
        result = asr_openai_audio.parse_verbose_json(doc, language="es", audio_ms=limit)
    except ProviderError as error:
        assert error.code == "no_word_timestamps" and doc["text"].strip() and not any(w.strip() for w, _s, _e in raw)
        return
    assert len(result.words) == sum(1 for w, _s, _e in raw if w.strip())
    for word in result.words:
        assert 0 <= word.start_ms <= word.end_ms <= limit


# --- merge_parts: offsets, monotonic non-overlapping times -------------------------------------------


def part(*words: tuple[str, int, int], audio_ms: int | None = None, language: str = "es") -> AsrResult:
    return AsrResult(tuple(AsrWord(t, s, e) for t, s, e in words), language, audio_ms=audio_ms)


def test_merge_parts_applies_offsets_and_keeps_every_word() -> None:
    merged = merge_parts(
        [part(("a", 100, 400), ("b", 500, 900), audio_ms=1000), part(("c", 50, 300), audio_ms=800)], [0, 1000]
    )
    assert [(w.text, w.start_ms, w.end_ms) for w in merged.words] == [
        ("a", 100, 400),
        ("b", 500, 900),
        ("c", 1050, 1300),
    ]
    assert merged.audio_ms == 1800 and merged.language == "es" and merged.diagnostics == {"parts": 2}


def test_merge_parts_orders_parts_by_offset() -> None:
    merged = merge_parts([part(("late", 0, 100)), part(("early", 0, 100))], [5000, 0])
    assert [w.text for w in merged.words] == ["early", "late"]


def test_merge_parts_trims_a_small_overlap_by_moving_the_earlier_end_back() -> None:
    merged = merge_parts([part(("a", 500, 1100)), part(("b", 0, 300))], [0, 1000])
    a, b = merged.words
    assert (a.start_ms, a.end_ms, a.timing_repaired) == (500, 1000, True)
    assert (b.start_ms, b.end_ms, b.timing_repaired) == (1000, 1300, False)  # the later word is never moved


def test_merge_parts_overlap_inside_a_part_is_trimmed_too() -> None:
    merged = merge_parts([part(("a", 0, 600), ("b", 450, 900))], [0])
    assert [(w.start_ms, w.end_ms) for w in merged.words] == [(0, 450), (450, 900)]


def test_merge_parts_refuses_to_hide_a_large_overlap() -> None:
    with pytest.raises(ProviderError) as caught:
        merge_parts([part(("a", 0, 3000)), part(("b", 0, 300))], [0, 1000])
    assert caught.value.code == "provider_invalid_output" and caught.value.reason == "overlapping_times"


def test_merge_parts_rejects_inconsistent_arguments() -> None:
    for results, offsets in (([], []), ([part(("a", 0, 1))], [0, 1]), ([part(("a", 0, 1))], [-1])):
        with pytest.raises(ValueError, match="invalid_parts"):
            merge_parts(results, offsets)


def test_merge_parts_language_is_the_first_determined_one() -> None:
    merged = merge_parts([part(("a", 0, 1), language="und"), part(("b", 0, 1), language="es")], [0, 100])
    assert merged.language == "es"


def test_merge_parts_reports_remote_deletion_across_parts() -> None:
    one = AsrResult((AsrWord("a", 0, 1),), "es", diagnostics={"remote_deleted": True})
    two = AsrResult((AsrWord("b", 0, 1),), "es", diagnostics={"remote_deleted": False})
    assert merge_parts([one, two], [0, 10]).diagnostics == {"parts": 2, "remote_deleted": False}


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(
    steps=st.lists(st.tuples(st.integers(0, 600), st.integers(0, 800), st.integers(0, 300)), min_size=1, max_size=15),
    cut=st.integers(0, 14),
)
def test_property_merged_words_are_monotonic_and_only_ever_shrink(steps: list[tuple[int, int, int]], cut: int) -> None:
    """Each word starts ``gap - overlap`` after the previous start+duration; overlaps stay within the trim limit."""
    words: list[tuple[str, int, int]] = []
    cursor = 0
    for index, (gap, duration, overlap) in enumerate(steps):
        start = max(cursor + gap - overlap, 0)
        words.append((f"w{index}", start, start + duration))
        cursor = start + duration
    cut = min(cut, len(words))
    first, second = words[:cut], words[cut:]
    offset = 0
    shifted = [(t, s - offset, e - offset) for t, s, e in second]
    parts = [part(*first), part(*shifted)] if first and second else [part(*words)]
    offsets = [0, offset] if first and second else [0]
    merged = merge_parts(parts, offsets)
    assert [w.text for w in merged.words] == [t for t, _s, _e in words]
    previous_end = 0
    for word, (_t, start, end) in zip(merged.words, words, strict=True):
        assert word.start_ms <= word.end_ms and word.start_ms >= previous_end
        assert word.start_ms <= start and word.end_ms <= end  # times only move earlier, never later
        previous_end = word.end_ms


# --- Property 4: no key, header or transcript text in logs or exceptions -------------------------------


def _all_text(error: BaseException) -> str:
    return "".join(traceback.format_exception(error)) + repr(error) + str(error) + repr(vars(error))


@pytest.mark.parametrize("transport", ["openai-audio", "assemblyai", "deepgram"])
@pytest.mark.parametrize("failure", ["http_error", "bad_json", "no_words", "success"])
async def test_property_4_nothing_sensitive_reaches_logs_or_exceptions(
    fake: FakeProvider,
    http: HttpTransport,
    audio: Path,
    fast_polling: None,
    caplog: pytest.LogCaptureFixture,
    transport: str,
    failure: str,
) -> None:
    echo = {
        "error": {"code": "x", "message": f"{KEY} Authorization: Bearer {KEY} {PHRASE}"},
        "err_msg": f"{KEY} {PHRASE}",
    }
    ok_openai = {**VERBOSE, "words": []} if failure == "no_words" else VERBOSE
    ok_deepgram = json.loads(json.dumps(DG_DONE))
    if failure == "no_words":
        ok_deepgram["results"]["channels"][0]["alternatives"][0]["words"] = []
    ok_assembly = {**AAI_DONE, "words": None} if failure == "no_words" else AAI_DONE
    if transport == "openai-audio":
        fake.routes[f"POST {GROQ_PATH}"] = (
            Reply(500, echo) if failure == "http_error"
            else Reply(raw=f"{KEY} {PHRASE}".encode()) if failure == "bad_json" else Reply(body=ok_openai)
        )  # fmt: skip
        run: Callable[[], Awaitable[AsrResult]] = lambda: openai_call(fake, http, audio)  # noqa: E731
    elif transport == "deepgram":
        fake.routes["POST /v1/listen"] = (
            Reply(500, echo) if failure == "http_error"
            else Reply(raw=f"{KEY} {PHRASE}".encode()) if failure == "bad_json" else Reply(body=ok_deepgram)
        )  # fmt: skip
        run = lambda: deepgram_call(fake, http, audio)  # noqa: E731
    else:
        AssemblyFake(fake, [Reply(body=ok_assembly)])
        if failure == "http_error":
            fake.routes["GET /v2/transcript/tr-1"] = [Reply(401, echo)]
        elif failure == "bad_json":
            fake.routes["GET /v2/transcript/tr-1"] = [Reply(raw=f"{KEY} {PHRASE}".encode())]
        run = lambda: assembly_call(fake, http, audio)  # noqa: E731
    caplog.set_level(logging.DEBUG)
    texts: list[str] = []
    try:
        result = await run()
        texts.append(repr(result.diagnostics))
    except ProviderError as error:
        texts.append(_all_text(error))
        assert failure != "success"
    else:
        assert failure == "success"
    texts.extend(record.getMessage() + repr(record.args) for record in caplog.records)
    joined = "\n".join(texts)
    assert KEY not in joined and PHRASE not in joined and "confidencial" not in joined and "Bearer" not in joined


def test_secret_record_never_prints_the_key() -> None:
    assert KEY not in repr(SECRET) and KEY not in str(SECRET)


# --- interface with the real SafeHttp of the host service --------------------------------------------


def _load_safe_http() -> Any:
    try:
        from sauri_engine_common.external.safe_http import SafeHttp  # type: ignore[import-not-found]  # noqa: PLC0415

        return SafeHttp
    except ImportError:
        pass
    path = Path(__file__).resolve().parents[2] / "host-engine" / "providers.py"
    spec = importlib.util.spec_from_file_location("providers_for_asr_adapters", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return getattr(module, "SafeHttp", None)


async def test_adapters_work_with_the_real_safe_http_transport(fake: FakeProvider, audio: Path) -> None:
    safe_http = _load_safe_http()
    if safe_http is None:
        pytest.skip("SafeHttp is not available")
    fake.routes[f"POST {GROQ_PATH}"] = Reply(body=VERBOSE)
    fake.routes["POST /v1/listen"] = Reply(body=DG_DONE)
    transport = safe_http()
    assert len((await openai_call(fake, transport, audio)).words) == 3
    assert len((await deepgram_call(fake, transport, audio)).words) == 3
    # The same transport enforces its address policy: a loopback target is refused without allow_local.
    route = make_route(fake, "deepgram")
    with pytest.raises(ProviderError) as caught:
        await asr_deepgram.transcribe(
            transport, audio, language="es", route=route, secret=SECRET, cancel=asyncio.Event(), allow_local=False
        )
    assert caught.value.code == "provider_bad_request"
