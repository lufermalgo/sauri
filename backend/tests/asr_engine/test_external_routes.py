"""The ASR gateway serves external routes with the same v2 body as the local engine (U4.3, #1117).

The provider is a fake on a random loopback port with the documented AssemblyAI shapes; whisper is never
started. Spanish quality and real limits are NO VERIFICADO until the owner's run (U10).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib.util
import logging
import sys
import time
from collections.abc import Iterator
from contextlib import nullcontext
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.external_asr_support import PHRASE, PROVIDER_KEY, FakeAssemblyAI, Served, serve, write_tone_wav

MODULE_PATH = Path(__file__).resolve().parents[2] / "asr-engine" / "native_main.py"
sys.path[:0] = [str(MODULE_PATH.parent), str(MODULE_PATH.parent.parent / "engine-common")]
SPEC = importlib.util.spec_from_file_location("native_asr_engine_external", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
native: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = native
SPEC.loader.exec_module(native)

import asr_external  # noqa: E402  (on sys.path through the line above)
from sauri_engine_common.external.asr_common import AsrWord, ProviderLimits  # noqa: E402
from sauri_engine_common.external.errors import ProviderError  # noqa: E402
from sauri_engine_common.route import Route, RouteTimeouts, encode_route  # noqa: E402
from sauri_engine_common.secrets import FileSecretStore, SecretRecord  # noqa: E402

from app.engines import capability_matrix  # noqa: E402

SECRET_REF = "sauri/owner-1/provider-1"
AUDIO_REF = "synthetic/recording.wav"


class SyntheticS3:
    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        return {"Body": BytesIO(b"synthetic audio")}


class Gateway:
    def __init__(self, tmp_path: Path, store: FileSecretStore) -> None:
        self.tmp_path = tmp_path
        self.store = store
        self.normalized_seconds = 3.0
        key = tmp_path / "capability_key"
        self.headers = {
            "Authorization": "Bearer synthetic-token",
            "X-Sauri-Recording-Capability": self._capability(key),
        }

    @staticmethod
    def _capability(key_path: Path) -> str:
        expires = int(time.time()) + 60
        signature = hmac.new(b"synthetic-secret", f"{AUDIO_REF}\n{expires}".encode(), hashlib.sha256).hexdigest()
        return f"{expires}.{signature}"

    def route(self, served: Served, **changes: Any) -> Route:
        route = Route(
            version=1, capability="transcription", kind="assemblyai", transport="assemblyai",
            base_url=served.url, model="universal-2", secret_ref=SECRET_REF, consent_version=1,
            timeouts=RouteTimeouts(total_s=30.0),
        )
        return replace(route, **changes)

    def store_key(self, served: Served, key: str = PROVIDER_KEY) -> None:
        self.store.put(SECRET_REF, SecretRecord(key=key, origin=served.url))

    async def post(self, route: Route | str | None, *, language: str = "es", headers: dict[str, str] | None = None,
                   audio_ref: str = AUDIO_REF) -> httpx.Response:
        sent = {**(self.headers if headers is None else headers)}
        if route is not None:
            sent["X-Sauri-Route"] = route if isinstance(route, str) else encode_route(route)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url="http://test") as client:
            return await client.post("/transcribe", json={"audio_ref": audio_ref, "language": language}, headers=sent)


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Gateway:
    monkeypatch.setenv("SAURI_ASR_VAD", "off")
    monkeypatch.setenv("SAURI_ASR_ALLOW_LOCAL_PROVIDERS", "1")
    token_path = tmp_path / "engine_token"
    token_path.write_text("synthetic-token")
    key_path = tmp_path / "capability_key"
    key_path.write_bytes(b"synthetic-secret")
    store = FileSecretStore(tmp_path / "secrets")
    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token_path)
    monkeypatch.setattr(native, "RECORDING_CAPABILITY_KEY_PATH", key_path)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "synthetic/")
    monkeypatch.setattr(native, "MINIO_BUCKET", "synthetic-bucket")
    monkeypatch.setattr(native, "s3_client", SyntheticS3())
    monkeypatch.setattr(native, "secret_store", store)
    monkeypatch.setattr(native, "KeepAwake", nullcontext)
    monkeypatch.setattr(native.tempfile, "tempdir", str(tmp_path))
    setup = Gateway(tmp_path, store)

    def normalize(source: Path, dest: Path, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(audio_ms=write_tone_wav(dest, setup.normalized_seconds), seconds=0.01)

    monkeypatch.setattr(native, "normalize_to_wav", normalize)
    return setup


@pytest.fixture
def provider() -> Iterator[tuple[FakeAssemblyAI, Served]]:
    fake = FakeAssemblyAI()
    with serve(fake.app()) as served:
        yield fake, served


async def test_external_route_returns_the_v2_body_with_remote_device_and_deletes_the_job(
    gateway: Gateway, provider: tuple[FakeAssemblyAI, Served], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    fake, served = provider
    gateway.store_key(served)
    caplog.set_level(logging.DEBUG)
    before = set(tmp_path.iterdir())
    response = await gateway.post(gateway.route(served))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["contract_version"] == 2 and data["language"] == "es"
    assert data["engine"] == {"name": "assemblyai", "model": "universal-2", "device": "remote"}
    spans = [(w["text"], w["start_ms"], w["end_ms"]) for w in data["words"]]
    assert spans == [("Hola", 100, 400), ("mundo.", 450, 900)]
    # AssemblyAI returns no segments: they come from the provider's own words and times.
    assert data["segments"] == [{"text": "Hola mundo.", "start_ms": 100, "end_ms": 900}]
    assert data["diagnostics"]["inverted_words"] == 0 and data["diagnostics"]["external"]["remote_deleted"] is True
    assert set(data["diagnostics"]["stage_ms"]) == {"download", "normalize", "prepare", "provider"}
    assert fake.deleted == ["job-0"]
    assert {s.authorization for s in fake.seen} == {PROVIDER_KEY}
    assert PROVIDER_KEY not in response.text and PROVIDER_KEY not in caplog.text
    assert PHRASE not in caplog.text and "Hola" not in caplog.text
    assert set(tmp_path.iterdir()) == before  # no audio, no part, no download survives


async def test_audio_reference_and_recording_capability_are_checked_before_the_route(
    gateway: Gateway, provider: tuple[FakeAssemblyAI, Served]
) -> None:
    fake, served = provider
    gateway.store_key(served)
    route = gateway.route(served)
    assert (await gateway.post(route, audio_ref="../other/recording.wav")).status_code == 400
    without_capability = {"Authorization": "Bearer synthetic-token"}
    assert (await gateway.post(route, headers=without_capability)).status_code == 403
    assert (await gateway.post(route, headers={})).status_code == 401
    assert fake.seen == []


@pytest.mark.parametrize(
    ("changes", "code", "status"),
    [
        ({"kind": "openai", "transport": "openai-chat"}, "provider_unsupported", 422),
        ({"kind": "deepgram"}, "provider_unsupported", 422),  # transport does not match the kind
        ({"consent_version": None}, "consent_missing", 422),
        ({"capability": "summary"}, "provider_unsupported", 422),
    ],
)
async def test_refused_routes_touch_neither_the_key_store_nor_the_provider(
    gateway: Gateway, provider: tuple[FakeAssemblyAI, Served], monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, Any], code: str, status: int,
) -> None:
    fake, served = provider
    gateway.store_key(served)
    reads: list[str] = []
    original = gateway.store.get
    monkeypatch.setattr(gateway.store, "get", lambda ref: reads.append(ref) or original(ref))
    response = await gateway.post(gateway.route(served, **changes))
    assert response.status_code == status
    assert response.json() == {"error": {"code": code, "retryable": False, "retry_after_s": None}}
    assert reads == [] and fake.seen == []


async def test_a_key_bound_to_another_origin_is_never_sent(
    gateway: Gateway, provider: tuple[FakeAssemblyAI, Served]
) -> None:
    fake, served = provider
    gateway.store.put(SECRET_REF, SecretRecord(key=PROVIDER_KEY, origin="https://api.assemblyai.com"))
    response = await gateway.post(gateway.route(served))
    assert response.status_code == 422 and response.json()["error"]["code"] == "origin_mismatch"
    assert fake.seen == []


async def test_missing_key_and_missing_secret_reference(
    gateway: Gateway, provider: tuple[FakeAssemblyAI, Served]
) -> None:
    fake, served = provider
    response = await gateway.post(gateway.route(served))  # nothing stored under the reference
    assert response.status_code == 503 and response.json()["error"]["code"] == "secret_unavailable"
    response = await gateway.post(gateway.route(served, secret_ref=None))
    assert response.status_code == 503 and response.json()["error"]["code"] == "secret_unavailable"
    assert fake.seen == []


async def test_plain_http_to_a_public_host_and_a_malformed_header_are_refused(gateway: Gateway) -> None:
    public_http = Route(
        version=1, capability="transcription", kind="assemblyai", transport="assemblyai",
        base_url="http://api.assemblyai.com", model="universal-2", secret_ref=SECRET_REF, consent_version=1,
    )
    response = await gateway.post(public_http)
    assert response.status_code == 422 and response.json()["error"]["code"] == "provider_bad_request"
    malformed = await gateway.post("not-a-route")
    assert malformed.status_code == 422 and malformed.json() == {"detail": "route_malformed"}


@pytest.mark.parametrize(
    ("setup", "status", "code", "retryable", "retry_after"),
    [
        ({"upload_status": 503}, 502, "provider_unavailable", True, None),
        ({"upload_status": 429, "upload_headers": {"Retry-After": "7"}}, 429, "provider_rate_limited", True, 7),
        ({"upload_status": 401}, 502, "provider_auth", False, None),
        ({"upload_status": 402}, 502, "provider_quota", True, None),
        ({"create_status": 400}, 502, "provider_bad_request", False, None),
    ],
)
async def test_provider_failures_keep_their_class_and_leak_nothing(
    gateway: Gateway, provider: tuple[FakeAssemblyAI, Served], caplog: pytest.LogCaptureFixture,
    setup: dict[str, Any], status: int, code: str, retryable: bool, retry_after: int | None,
) -> None:
    fake, served = provider
    for name, value in setup.items():
        setattr(fake, name, value)
    gateway.store_key(served)
    caplog.set_level(logging.DEBUG)
    response = await gateway.post(gateway.route(served))
    assert response.status_code == status
    assert response.json() == {"error": {"code": code, "retryable": retryable, "retry_after_s": retry_after}}
    assert PROVIDER_KEY not in response.text and PROVIDER_KEY not in caplog.text


async def test_silence_is_no_speech_like_the_local_engine(
    gateway: Gateway, provider: tuple[FakeAssemblyAI, Served]
) -> None:
    fake, served = provider
    fake.words_for, fake.include_text = (lambda n: []), False
    gateway.store_key(served)
    response = await gateway.post(gateway.route(served))
    assert response.status_code == 422 and response.json() == {"detail": "no_speech"}
    assert fake.deleted == ["job-0"]


async def test_text_without_word_times_is_refused_not_invented(
    gateway: Gateway, provider: tuple[FakeAssemblyAI, Served]
) -> None:
    fake, served = provider
    fake.words_for, fake.text = (lambda n: []), PHRASE
    gateway.store_key(served)
    response = await gateway.post(gateway.route(served))
    assert response.status_code == 502 and response.json()["error"]["code"] == "no_word_timestamps"


async def test_long_audio_is_split_and_merged_on_the_original_clock(
    gateway: Gateway, provider: tuple[FakeAssemblyAI, Served], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake, served = provider
    fake.words_for = lambda n: [(f"parte{n}", 1000, 1500)]
    gateway.normalized_seconds = 40.0
    gateway.store_key(served)
    # A provider that accepts 15 s per part: 40 s of audio need several parts at voice-less hard cuts.
    entry = asr_external._TRANSPORTS["assemblyai"]
    monkeypatch.setitem(asr_external._TRANSPORTS, "assemblyai", (ProviderLimits(None, 15), entry[1]))
    response = await gateway.post(gateway.route(served))
    assert response.status_code == 200, response.text
    data = response.json()
    texts = [w["text"] for w in data["words"]]
    starts = [w["start_ms"] for w in data["words"]]
    assert texts == [f"parte{i}" for i in range(len(texts))] and len(texts) >= 3
    assert starts == sorted(starts) and starts[0] == 1000 and starts[1] > 5_000  # offsets applied once
    assert data["diagnostics"]["external"]["parts"] == len(texts)
    assert fake.deleted == [f"job-{i}" for i in range(len(texts))]


async def test_word_level_answers_larger_than_the_default_cap_are_read(
    gateway: Gateway, provider: tuple[FakeAssemblyAI, Served]
) -> None:
    fake, served = provider
    fake.padding_bytes = 3 * 1024 * 1024  # over SafeHttp's default 2 MiB
    gateway.store_key(served)
    response = await gateway.post(gateway.route(served))
    assert response.status_code == 200, response.text


async def test_the_default_cap_still_refuses_oversized_bodies(provider: tuple[FakeAssemblyAI, Served]) -> None:
    from sauri_engine_common.external.safe_http import MAX_RESPONSE_BYTES, SafeHttp

    fake, served = provider
    fake.padding_bytes = MAX_RESPONSE_BYTES + 1
    fake.created = 1  # a transcript id exists: poll it directly
    url = f"{served.url}/v2/transcript/job-0"

    def get(http: SafeHttp) -> Any:
        return http.request("GET", url, headers={}, allow_local=True, total_timeout_s=10)

    with pytest.raises(ProviderError) as refused:
        await get(SafeHttp())
    assert refused.value.reason == "response_too_large"
    assert (await get(SafeHttp(max_response_bytes=MAX_RESPONSE_BYTES * 2))).status == 200


async def test_cancellation_aborts_the_provider_call_and_deletes_the_remote_job(
    gateway: Gateway, provider: tuple[FakeAssemblyAI, Served], tmp_path: Path
) -> None:
    from sauri_engine_common.external.safe_http import SafeHttp

    fake, served = provider
    fake.hang = True
    gateway.store_key(served)
    wav = tmp_path / "audio.wav"
    write_tone_wav(wav, 3.0)
    cancel = asyncio.Event()
    task = asyncio.create_task(
        asr_external.transcribe_external(
            http=SafeHttp(), route=gateway.route(served), secret=SecretRecord(PROVIDER_KEY, served.url),
            wav=wav, language="es", cancel=cancel, deadline_s=30.0, allow_local=True,
        )
    )
    for _ in range(300):
        if fake.polls:
            break
        await asyncio.sleep(0.01)
    assert fake.polls and not fake.deleted
    cancel.set()
    with pytest.raises(asr_external.AdapterCancelled):
        await asyncio.wait_for(task, timeout=10)
    assert fake.deleted == ["job-0"]


async def test_client_disconnect_sets_the_cancel_event() -> None:
    answers = iter([False, False, True])

    async def is_disconnected() -> bool:
        return next(answers)

    cancel = asyncio.Event()
    await asyncio.wait_for(asr_external.watch_disconnect(is_disconnected, cancel, interval_s=0.001), timeout=5)
    assert cancel.is_set()


async def test_deadline_is_a_timeout_class_not_a_hang(
    gateway: Gateway, provider: tuple[FakeAssemblyAI, Served]
) -> None:
    fake, served = provider
    fake.hang = True
    gateway.store_key(served)
    response = await gateway.post(gateway.route(served, timeouts=RouteTimeouts(total_s=2.0)))
    assert response.status_code == 504 and response.json()["error"]["code"] == "provider_timeout"
    assert fake.deleted == ["job-0"]


def test_gateway_matrix_is_the_api_matrix_for_transcription() -> None:
    api = {
        (kind, support.transport)
        for kind, entries in capability_matrix.MATRIX.items()
        if (support := entries.get("transcription")) is not None and capability_matrix.is_offered(kind, "transcription")
    }
    assert api == set(asr_external.SUPPORTED)
    matrix = asr_external.GatewayMatrix()
    assert not matrix.supports("assemblyai", "diarization", "assemblyai")
    assert not matrix.supports("openai", "transcription", "openai-audio")


@given(
    st.lists(
        st.tuples(st.text(alphabet="abcdef.,?!", min_size=1, max_size=6), st.integers(0, 4000), st.integers(0, 800)),
        max_size=60,
    )
)
def test_segments_from_words_keep_every_word_and_only_provider_times(raw: list[tuple[str, int, int]]) -> None:
    words: list[AsrWord] = []
    cursor = 0
    for text, gap, length in raw:
        cursor += gap
        words.append(AsrWord(text, cursor, cursor + length))
        cursor += length
    segments = asr_external.segments_from_words(words)
    assert [t for s in segments for t in s.text.split(" ")] == [w.text for w in words]
    times = {t for w in words for t in (w.start_ms, w.end_ms)}
    assert all(s.start_ms in times and s.end_ms in times and s.start_ms <= s.end_ms for s in segments)
    assert [s.start_ms for s in segments] == sorted(s.start_ms for s in segments)


def test_provider_errors_map_to_http_status() -> None:
    assert asr_external.error_status(ProviderError("provider_rate_limited")) == 429
    assert asr_external.error_status(ProviderError("provider_timeout")) == 504
    assert asr_external.error_status(ProviderError("audio_too_large")) == 413
    assert asr_external.error_status(ProviderError("provider_unavailable")) == 502
