"""The diarization gateway serves external routes with the same v2 body as the local engine (U5.2, #1138).

The provider is a fake on a random loopback port with the documented Deepgram and AssemblyAI shapes; Senko is
never started. Spanish quality and real limits are NO VERIFICADO until the owner's run (U10).
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
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import httpx
import pytest

from tests.external_asr_support import PHRASE, PROVIDER_KEY, FakeAssemblyAI, Served, serve, write_tone_wav
from tests.external_diar_support import FakeDeepgram

MODULE_PATH = Path(__file__).resolve().parents[2] / "diar-engine" / "native_main.py"
sys.path[:0] = [str(MODULE_PATH.parent), str(MODULE_PATH.parent.parent / "engine-common")]
SPEC = importlib.util.spec_from_file_location("native_diar_engine_external", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
native: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = native
SPEC.loader.exec_module(native)

import diar_external  # noqa: E402  (on sys.path through the line above)
from sauri_engine_common.external.asr_common import AdapterCancelled, ProviderLimits  # noqa: E402
from sauri_engine_common.external.errors import ProviderError  # noqa: E402
from sauri_engine_common.route import Route, RouteTimeouts, encode_route  # noqa: E402
from sauri_engine_common.secrets import FileSecretStore, SecretRecord  # noqa: E402

from app.engines import capability_matrix  # noqa: E402

SECRET_REF = "sauri/owner-1/provider-1"
AUDIO_REF = "synthetic/recording.wav"


class SyntheticS3:
    def download_file(self, bucket: str, audio_ref: str, path: str) -> None:
        assert (bucket, audio_ref) == ("synthetic-bucket", AUDIO_REF)
        Path(path).write_bytes(b"synthetic audio")


class Gateway:
    def __init__(self, store: FileSecretStore) -> None:
        self.store = store
        self.normalized_seconds = 3.0
        expires = int(time.time()) + 60
        signature = hmac.new(b"synthetic-secret", f"{AUDIO_REF}\n{expires}".encode(), hashlib.sha256).hexdigest()
        self.headers = {
            "Authorization": "Bearer synthetic-token",
            "X-Sauri-Recording-Capability": f"{expires}.{signature}",
        }

    def route(self, served: Served, **changes: Any) -> Route:
        route = Route(
            version=1, capability="diarization", kind="deepgram", transport="deepgram",
            base_url=served.url, model="nova-3", secret_ref=SECRET_REF, consent_version=1,
            timeouts=RouteTimeouts(total_s=30.0),
        )
        return replace(route, **changes)

    def assemblyai_route(self, served: Served, **changes: Any) -> Route:
        return self.route(served, kind="assemblyai", transport="assemblyai", model="universal-2", **changes)

    def store_key(self, served: Served, key: str = PROVIDER_KEY) -> None:
        self.store.put(SECRET_REF, SecretRecord(key=key, origin=served.url))

    async def post(self, route: Route | str | None, *, headers: dict[str, str] | None = None,
                   audio_ref: str = AUDIO_REF) -> httpx.Response:
        sent = {**(self.headers if headers is None else headers)}
        if route is not None:
            sent["X-Sauri-Route"] = route if isinstance(route, str) else encode_route(route)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url="http://test") as client:
            return await client.post("/diarize", json={"audio_ref": audio_ref}, headers=sent)


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Gateway:
    monkeypatch.setenv("SAURI_DIAR_ALLOW_LOCAL_PROVIDERS", "1")
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
    setup = Gateway(store)

    def normalize(source: Path, dest: Path, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(audio_ms=write_tone_wav(dest, setup.normalized_seconds), seconds=0.01)

    monkeypatch.setattr(native, "normalize_to_wav", normalize)
    return setup


@pytest.fixture
def deepgram() -> Iterator[tuple[FakeDeepgram, Served]]:
    fake = FakeDeepgram()
    with serve(fake.app()) as served:
        yield fake, served


@pytest.fixture
def assemblyai() -> Iterator[tuple[FakeAssemblyAI, Served]]:
    fake = FakeAssemblyAI(speakers_for=lambda n: ["A", "B"])
    with serve(fake.app()) as served:
        yield fake, served


async def test_external_route_returns_the_v2_body_with_remote_device(
    gateway: Gateway, deepgram: tuple[FakeDeepgram, Served], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    fake, served = deepgram
    gateway.store_key(served)
    caplog.set_level(logging.DEBUG)
    before = set(tmp_path.iterdir())
    response = await gateway.post(gateway.route(served))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["contract_version"] == 2
    assert data["engine"] == {"name": "deepgram", "model": "nova-3", "device": "remote"}
    assert data["segments"] == [
        {"speaker": "0", "start_ms": 100, "end_ms": 400},
        {"speaker": "1", "start_ms": 450, "end_ms": 900},
    ]
    assert data["speaker_count"] == 2
    external = data["diagnostics"]["external"]
    assert (external["parts"], external["label_policy"], external["speaker_count_per_part"]) == (1, "provider", [2])
    assert data["diagnostics"]["audio_ms"] == 3000 and data["diagnostics"]["dropped_segments"] == 0
    assert set(data["diagnostics"]["stage_ms"]) == {"download", "normalize", "prepare", "provider"}
    assert set(data) == {"contract_version", "segments", "speaker_count", "engine", "diagnostics"}  # the local keys
    assert fake.authorizations == [f"Token {PROVIDER_KEY}"]
    assert fake.queries[0]["diarize_model"] == ["latest"]
    assert PROVIDER_KEY not in response.text and PROVIDER_KEY not in caplog.text
    assert "Hola" not in response.text and "Hola" not in caplog.text
    assert set(tmp_path.iterdir()) == before  # no audio, no part, no download survives


async def test_assemblyai_route_labels_speakers_and_deletes_the_remote_job(
    gateway: Gateway, assemblyai: tuple[FakeAssemblyAI, Served]
) -> None:
    fake, served = assemblyai
    gateway.store_key(served)
    response = await gateway.post(gateway.assemblyai_route(served))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["engine"] == {"name": "assemblyai", "model": "universal-2", "device": "remote"}
    assert data["segments"] == [
        {"speaker": "A", "start_ms": 100, "end_ms": 400},
        {"speaker": "B", "start_ms": 450, "end_ms": 900},
    ]
    assert data["diagnostics"]["external"]["remote_deleted"] is True
    assert fake.deleted == ["job-0"] and {s.authorization for s in fake.seen} == {PROVIDER_KEY}


async def test_a_local_route_is_the_local_engine_and_never_calls_a_provider(
    gateway: Gateway, deepgram: tuple[FakeDeepgram, Served], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake, _served = deepgram
    monkeypatch.setattr(native, "diarization_pipeline", SimpleNamespace(
        diarize=lambda *, wav_path, accurate, generate_colors: {
            "raw_segments": [{"start": 0.5, "end": 2.25, "speaker": "SPEAKER_00"}], "merged_segments": []}
    ))
    local = Route(version=1, capability="diarization", kind="local", transport=None, base_url=None,
                  model="local:default", secret_ref=None, consent_version=None)
    for header in (None, local):
        response = await gateway.post(header)
        assert response.status_code == 200, response.text
        assert response.json()["engine"] == {"name": "senko", "model": "senko-coreml", "device": "coreml"}
    assert fake.requests == 0


async def test_audio_reference_and_recording_capability_are_checked_before_the_route(
    gateway: Gateway, deepgram: tuple[FakeDeepgram, Served]
) -> None:
    fake, served = deepgram
    gateway.store_key(served)
    route = gateway.route(served)
    assert (await gateway.post(route, audio_ref="../other/recording.wav")).status_code == 400
    assert (await gateway.post(route, headers={"Authorization": "Bearer synthetic-token"})).status_code == 403
    assert (await gateway.post(route, headers={})).status_code == 401
    assert fake.requests == 0


@pytest.mark.parametrize(
    ("changes", "code", "status"),
    [
        ({"kind": "openai", "transport": "openai-chat"}, "provider_unsupported", 422),
        ({"kind": "groq", "transport": "openai-audio"}, "provider_unsupported", 422),  # no diarization rows
        ({"transport": "assemblyai"}, "provider_unsupported", 422),  # transport does not match the kind
        ({"consent_version": None}, "consent_missing", 422),
        ({"capability": "transcription"}, "provider_unsupported", 422),
        ({"capability": "summary"}, "provider_unsupported", 422),
    ],
)
async def test_refused_routes_touch_neither_the_key_store_nor_the_provider(
    gateway: Gateway, deepgram: tuple[FakeDeepgram, Served], monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, Any], code: str, status: int,
) -> None:
    fake, served = deepgram
    gateway.store_key(served)
    reads: list[str] = []
    original = gateway.store.get
    monkeypatch.setattr(gateway.store, "get", lambda ref: reads.append(ref) or original(ref))
    response = await gateway.post(gateway.route(served, **changes))
    assert response.status_code == status
    assert response.json() == {"error": {"code": code, "retryable": False, "retry_after_s": None}}
    assert reads == [] and fake.requests == 0


async def test_a_key_bound_to_another_origin_is_never_sent(
    gateway: Gateway, deepgram: tuple[FakeDeepgram, Served]
) -> None:
    fake, served = deepgram
    gateway.store.put(SECRET_REF, SecretRecord(key=PROVIDER_KEY, origin="https://api.deepgram.com"))
    response = await gateway.post(gateway.route(served))
    assert response.status_code == 422 and response.json()["error"]["code"] == "origin_mismatch"
    assert fake.requests == 0


async def test_missing_key_and_missing_secret_reference(
    gateway: Gateway, deepgram: tuple[FakeDeepgram, Served]
) -> None:
    fake, served = deepgram
    response = await gateway.post(gateway.route(served))  # nothing stored under the reference
    assert response.status_code == 503 and response.json()["error"]["code"] == "secret_unavailable"
    response = await gateway.post(gateway.route(served, secret_ref=None))
    assert response.status_code == 503 and response.json()["error"]["code"] == "secret_unavailable"
    assert fake.requests == 0


async def test_plain_http_to_a_public_host_and_a_malformed_header_are_refused(gateway: Gateway) -> None:
    public_http = Route(
        version=1, capability="diarization", kind="deepgram", transport="deepgram",
        base_url="http://api.deepgram.com", model="nova-3", secret_ref=SECRET_REF, consent_version=1,
    )
    response = await gateway.post(public_http)
    assert response.status_code == 422 and response.json()["error"]["code"] == "provider_bad_request"
    malformed = await gateway.post("not-a-route")
    assert malformed.status_code == 422 and malformed.json() == {"detail": "route_malformed"}


@pytest.mark.parametrize(
    ("setup", "status", "code", "retryable", "retry_after"),
    [
        ({"status": 503}, 502, "provider_unavailable", True, None),
        ({"status": 429, "headers": {"Retry-After": "7"}}, 429, "provider_rate_limited", True, 7),
        ({"status": 401}, 502, "provider_auth", False, None),
        ({"status": 402}, 502, "provider_quota", True, None),
        ({"status": 400}, 502, "provider_bad_request", False, None),
    ],
)
async def test_provider_failures_keep_their_class_and_leak_nothing(
    gateway: Gateway, deepgram: tuple[FakeDeepgram, Served], caplog: pytest.LogCaptureFixture,
    setup: dict[str, Any], status: int, code: str, retryable: bool, retry_after: int | None,
) -> None:
    fake, served = deepgram
    for name, value in setup.items():
        setattr(fake, name, value)
    gateway.store_key(served)
    caplog.set_level(logging.DEBUG)
    response = await gateway.post(gateway.route(served))
    assert response.status_code == status
    assert response.json() == {"error": {"code": code, "retryable": retryable, "retry_after_s": retry_after}}
    assert PROVIDER_KEY not in response.text and PROVIDER_KEY not in caplog.text


async def test_silence_is_an_empty_result_like_the_local_engine(
    gateway: Gateway, deepgram: tuple[FakeDeepgram, Served]
) -> None:
    fake, served = deepgram
    fake.words_for = lambda n: []
    gateway.store_key(served)
    response = await gateway.post(gateway.route(served))
    assert response.status_code == 200
    assert (response.json()["segments"], response.json()["speaker_count"]) == ([], 0)


async def test_speech_without_speaker_labels_is_refused_not_invented(
    gateway: Gateway, deepgram: tuple[FakeDeepgram, Served]
) -> None:
    fake, served = deepgram
    fake.words_for = lambda n: [(None, PHRASE, 0.1, 0.9)]
    gateway.store_key(served)
    response = await gateway.post(gateway.route(served))
    assert response.status_code == 502 and response.json()["error"]["code"] == "provider_invalid_output"


async def test_segments_without_duration_are_dropped_and_counted_like_the_local_engine(
    gateway: Gateway, deepgram: tuple[FakeDeepgram, Served]
) -> None:
    fake, served = deepgram
    fake.words_for = lambda n: [(0, "uno", 0.1, 0.5), (1, "dos", 0.7, 0.7), (0, "tres", 0.9, 1.2)]
    gateway.store_key(served)
    data = (await gateway.post(gateway.route(served))).json()
    assert [s["speaker"] for s in data["segments"]] == ["0", "0"]  # speaker 1 only spoke for zero time
    assert data["speaker_count"] == 1 and data["diagnostics"]["dropped_segments"] == 1


async def test_long_audio_is_split_and_labels_stay_distinct_per_part(
    gateway: Gateway, deepgram: tuple[FakeDeepgram, Served], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake, served = deepgram
    fake.words_for = lambda n: [(0, "uno", 1.0, 1.5), (1, "dos", 2.0, 2.5)]
    gateway.normalized_seconds = 40.0
    gateway.store_key(served)
    entry = diar_external._TRANSPORTS["deepgram"]
    monkeypatch.setitem(diar_external._TRANSPORTS, "deepgram", (ProviderLimits(None, 15), entry[1]))
    response = await gateway.post(gateway.route(served))
    assert response.status_code == 200, response.text
    data = response.json()
    parts = data["diagnostics"]["external"]["parts"]
    assert parts >= 3 and fake.requests == parts
    labels = [s["speaker"] for s in data["segments"]]
    assert labels[:2] == ["p1.0", "p1.1"] and f"p{parts}.0" in labels
    starts = [s["start_ms"] for s in data["segments"]]
    assert starts == sorted(starts) and starts[0] == 1000 and starts[2] > 5_000  # offsets applied once
    # The merged count over-counts real people (two here): it is reported, not hidden.
    assert data["speaker_count"] == 2 * parts
    assert data["diagnostics"]["external"]["label_policy"] == "per_part"
    assert data["diagnostics"]["external"]["speaker_count_per_part"] == [2] * parts


async def test_cancellation_aborts_the_provider_call_and_deletes_the_remote_job(
    gateway: Gateway, assemblyai: tuple[FakeAssemblyAI, Served], tmp_path: Path
) -> None:
    from sauri_engine_common.external.safe_http import SafeHttp

    fake, served = assemblyai
    fake.hang = True
    wav = tmp_path / "audio.wav"
    write_tone_wav(wav, 3.0)
    cancel = asyncio.Event()
    task = asyncio.create_task(
        diar_external.diarize_external(
            http=SafeHttp(), route=gateway.assemblyai_route(served), secret=SecretRecord(PROVIDER_KEY, served.url),
            wav=wav, cancel=cancel, deadline_s=30.0, allow_local=True,
        )
    )
    for _ in range(300):
        if fake.polls:
            break
        await asyncio.sleep(0.01)
    assert fake.polls and not fake.deleted
    cancel.set()
    with pytest.raises(AdapterCancelled):
        await asyncio.wait_for(task, timeout=10)
    assert fake.deleted == ["job-0"]


async def test_client_disconnect_sets_the_cancel_event() -> None:
    answers = iter([False, False, True])

    async def is_disconnected() -> bool:
        return next(answers)

    cancel = asyncio.Event()
    await asyncio.wait_for(diar_external.watch_disconnect(is_disconnected, cancel, interval_s=0.001), timeout=5)
    assert cancel.is_set()


async def test_deadline_is_a_timeout_class_not_a_hang(
    gateway: Gateway, assemblyai: tuple[FakeAssemblyAI, Served]
) -> None:
    fake, served = assemblyai
    fake.hang = True
    gateway.store_key(served)
    response = await gateway.post(gateway.assemblyai_route(served, timeouts=RouteTimeouts(total_s=2.0)))
    assert response.status_code == 504 and response.json()["error"]["code"] == "provider_timeout"
    assert fake.deleted == ["job-0"]


def test_gateway_matrix_is_the_api_matrix_for_diarization() -> None:
    api = {
        (kind, support.transport)
        for kind, entries in capability_matrix.MATRIX.items()
        if (support := entries.get("diarization")) is not None
    }
    assert api == set(diar_external.SUPPORTED)
    matrix = diar_external.GatewayMatrix()
    assert not matrix.supports("assemblyai", "transcription", "assemblyai")
    assert not matrix.supports("openai", "diarization", "openai-audio")


def test_provider_errors_map_to_http_status() -> None:
    assert diar_external.error_status(ProviderError("provider_rate_limited")) == 429
    assert diar_external.error_status(ProviderError("provider_timeout")) == 504
    assert diar_external.error_status(ProviderError("audio_too_large")) == 413
    assert diar_external.error_status(ProviderError("provider_unavailable")) == 502
