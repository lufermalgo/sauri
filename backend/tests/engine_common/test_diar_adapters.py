"""External speaker diarization adapters against fake providers on 127.0.0.1 (no real provider, key or audio).

The fakes mimic the documented answer shapes (AssemblyAI upload, transcript with ``speaker_labels`` and delete;
Deepgram ``/v1/listen`` with ``diarize_model``) and always carry provider text, which must never reach a result,
a log or an exception. The audio is placeholder bytes. Spanish diarization quality and the real limits are
NO VERIFICADO until U10; nothing here proves them.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import time
import traceback
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sauri_engine_common.external import asr_assemblyai, diar_assemblyai, diar_deepgram
from sauri_engine_common.external.asr_common import AdapterCancelled, HttpTransport
from sauri_engine_common.external.errors import ProviderError
from sauri_engine_common.external.safe_http import SafeHttp
from sauri_engine_common.external.speakers import (
    DiarResult,
    LabeledWord,
    SpeakerSegment,
    build_result,
    merge_parts,
    safe_label,
    union_runs,
)
from sauri_engine_common.route import Route, RouteTimeouts

from tests.engine_common.test_asr_adapters import KEY, PHRASE, SECRET, FakeProvider, LoopbackHttp, Reply, Seen

Seg = SpeakerSegment

# --- fixtures ----------------------------------------------------------------------------------------


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


@pytest.fixture
def fast_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asr_assemblyai, "POLL_INITIAL_S", 0.01)
    monkeypatch.setattr(asr_assemblyai, "POLL_MAX_S", 0.02)


def make_route(fake: FakeProvider, transport: str, *, model: str = "model-x", total_s: float = 5.0) -> Route:
    return Route(
        version=1,
        capability="diarization",
        kind="test",
        transport=transport,  # type: ignore[arg-type]
        base_url=fake.url,
        model=model,
        secret_ref=None,
        consent_version=1,
        timeouts=RouteTimeouts(connect_s=2.0, first_byte_s=2.0, idle_s=2.0, total_s=total_s),
    )


# --- AssemblyAI fake -----------------------------------------------------------------------------------

AAI_DONE: dict[str, Any] = {
    "id": "tr-1",
    "status": "completed",
    "language_code": "es",
    "audio_duration": 5,
    "text": f"hola {PHRASE}",
    "words": [
        {"text": "hola", "start": 200, "end": 640, "confidence": 0.98, "speaker": "A"},
        {"text": "frase", "start": 2100, "end": 2500, "confidence": 0.91, "speaker": "B"},
        {"text": "confidencial", "start": 2600, "end": 3400, "confidence": 0.9, "speaker": "B"},
        {"text": "gracias", "start": 3500, "end": 3900, "confidence": 0.9, "speaker": "A"},
    ],
    "utterances": [
        {"text": "hola", "start": 200, "end": 640, "speaker": "A", "confidence": 0.9, "words": []},
        {"text": PHRASE, "start": 2100, "end": 3400, "speaker": "B", "confidence": 0.9, "words": []},
        {"text": "gracias", "start": 3500, "end": 3900, "speaker": "A", "confidence": 0.9, "words": []},
    ],
}
AAI_SEGMENTS = (Seg("A", 200, 640), Seg("B", 2100, 3400), Seg("A", 3500, 3900))


class AssemblyFake:
    """Provider state: transcript statuses served in order, and what was deleted."""

    def __init__(self, fake: FakeProvider, statuses: list[Reply]) -> None:
        self.deleted: list[str] = []
        fake.routes["POST /v2/upload"] = Reply(body={"upload_url": "https://cdn.example.test/upload/abc"})
        fake.routes["POST /v2/transcript"] = Reply(body={"id": "tr-1", "status": "queued"})
        fake.routes["GET /v2/transcript/tr-1"] = statuses
        fake.routes["DELETE /v2/transcript/tr-1"] = self._delete

    def _delete(self, _request: Seen) -> Reply:
        self.deleted.append("tr-1")
        return Reply(body={"id": "tr-1", "status": "completed", "text": None, "words": None})


async def assembly_call(fake: FakeProvider, http: HttpTransport, audio: Path, **kwargs: Any) -> DiarResult:
    route = make_route(fake, "assemblyai", model=kwargs.pop("model", "universal-2"), total_s=kwargs.pop("total_s", 5.0))
    cancel = kwargs.pop("cancel", None) or asyncio.Event()
    return await diar_assemblyai.diarize(
        http, audio, route=route, secret=SECRET, cancel=cancel, allow_local=True, **kwargs
    )


async def wait_polled(fake: FakeProvider) -> None:
    deadline = time.monotonic() + 2
    while not fake.calls("GET", "/v2/transcript/tr-1"):
        assert time.monotonic() < deadline
        await asyncio.sleep(0.01)


async def test_assemblyai_sends_speaker_labels_and_returns_one_segment_per_run(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    state = AssemblyFake(fake, [Reply(body={"id": "tr-1", "status": "processing"}), Reply(body=AAI_DONE)])
    result = await assembly_call(fake, http, audio, language="es", speakers_expected=2, audio_ms=5000)
    assert result.segments == AAI_SEGMENTS and result.speaker_count == 2 and result.audio_ms == 5000
    assert result.diagnostics["remote_deleted"] is True and state.deleted == ["tr-1"]
    upload, create = fake.calls("POST", "/v2/upload")[0], fake.calls("POST", "/v2/transcript")[0]
    assert upload.headers["authorization"] == KEY and upload.body == audio.read_bytes()
    assert json.loads(create.body) == {
        "speech_models": ["universal-2"],
        "language_code": "es",
        "speaker_labels": True,
        "speakers_expected": 2,
        "audio_url": "https://cdn.example.test/upload/abc",
    }


async def test_assemblyai_defaults_to_language_detection_and_no_speaker_count(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    AssemblyFake(fake, [Reply(body=AAI_DONE)])
    result = await assembly_call(fake, http, audio)
    assert json.loads(fake.calls("POST", "/v2/transcript")[0].body) == {
        "speech_models": ["universal-2"],
        "language_detection": True,
        "speaker_labels": True,
        "audio_url": "https://cdn.example.test/upload/abc",
    }
    assert result.audio_ms == 6000  # the provider duration rounded up, when the caller gives none


@pytest.mark.parametrize("expected", [0, -1, 101, True])
async def test_assemblyai_refuses_an_unusable_speaker_count_before_any_call(
    fake: FakeProvider, http: HttpTransport, audio: Path, expected: int
) -> None:
    with pytest.raises(ProviderError) as caught:
        await assembly_call(fake, http, audio, speakers_expected=expected)
    assert (caught.value.code, caught.value.reason) == ("provider_bad_request", "invalid_speakers_expected")
    assert fake.seen == []


async def test_assemblyai_uses_utterances_only_when_there_are_no_words(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    AssemblyFake(fake, [Reply(body={**AAI_DONE, "words": None})])
    assert (await assembly_call(fake, http, audio)).segments == AAI_SEGMENTS


async def test_assemblyai_skips_words_without_a_label_and_counts_them(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    words = [{**w} for w in AAI_DONE["words"]]
    words[2]["speaker"] = None
    AssemblyFake(fake, [Reply(body={**AAI_DONE, "words": words})])
    result = await assembly_call(fake, http, audio)
    assert result.segments == (Seg("A", 200, 640), Seg("B", 2100, 2500), Seg("A", 3500, 3900))
    assert result.diagnostics["unlabeled_words"] == 1


async def test_assemblyai_speech_without_any_label_is_invalid_output(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    unlabeled = [{k: v for k, v in w.items() if k != "speaker"} for w in AAI_DONE["words"]]
    state = AssemblyFake(fake, [Reply(body={**AAI_DONE, "words": unlabeled, "utterances": None})])
    with pytest.raises(ProviderError) as caught:
        await assembly_call(fake, http, audio)
    assert (caught.value.code, caught.value.reason) == ("provider_invalid_output", "no_speaker_labels")
    assert state.deleted == ["tr-1"]
    state = AssemblyFake(fake, [Reply(body={**AAI_DONE, "words": [], "utterances": []})])  # text but no words
    with pytest.raises(ProviderError) as text_only:
        await assembly_call(fake, http, audio)
    assert text_only.value.reason == "no_speaker_labels" and state.deleted == ["tr-1"]


async def test_assemblyai_silence_is_an_empty_result(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    silent = {"id": "tr-1", "status": "completed", "text": "", "words": [], "utterances": [], "audio_duration": 3}
    AssemblyFake(fake, [Reply(body=silent)])
    result = await assembly_call(fake, http, audio)
    assert result.segments == () and result.speaker_count == 0


@pytest.mark.parametrize("label", ["A B", "x" * 17, f"{PHRASE}", "", 1.5, ["A"], {"x": 1}, True])
async def test_assemblyai_refuses_a_label_that_could_carry_content(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None, label: object
) -> None:
    words = [{**AAI_DONE["words"][0], "speaker": label}]
    AssemblyFake(fake, [Reply(body={**AAI_DONE, "words": words})])
    with pytest.raises(ProviderError) as caught:
        await assembly_call(fake, http, audio)
    assert (caught.value.code, caught.value.reason) == ("provider_invalid_output", "bad_speaker_label")
    assert PHRASE not in repr(vars(caught.value))


async def test_assemblyai_unexpected_shapes_are_invalid_output(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    for broken in ({"words": "x"}, {"words": [1]}, {"words": [], "utterances": {"a": 1}}):
        AssemblyFake(fake, [Reply(body={**AAI_DONE, **broken})])
        with pytest.raises(ProviderError) as caught:
            await assembly_call(fake, http, audio)
        assert caught.value.code == "provider_invalid_output"


async def test_assemblyai_classifies_provider_answers(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    AssemblyFake(fake, [Reply(body=AAI_DONE)])
    fake.routes["POST /v2/transcript"] = Reply(429, {"error": "slow down"}, headers={"Retry-After": "11"})
    with pytest.raises(ProviderError) as limited:
        await assembly_call(fake, http, audio)
    assert (limited.value.code, limited.value.retry_after_s) == ("provider_rate_limited", 11)
    assert fake.calls("DELETE", "/v2/") == []  # no transcript id yet: nothing to delete
    fake.routes["POST /v2/upload"] = Reply(401, {"error": "Invalid API key"})
    with pytest.raises(ProviderError) as auth:
        await assembly_call(fake, http, audio)
    assert auth.value.code == "provider_auth"
    state = AssemblyFake(fake, [Reply(body={"id": "tr-1", "status": "error", "error": f"roto: {PHRASE}"})])
    with pytest.raises(ProviderError) as failed:
        await assembly_call(fake, http, audio)
    assert (failed.value.code, failed.value.reason) == ("provider_bad_request", "job_failed")
    assert state.deleted == ["tr-1"]


async def test_assemblyai_upload_timeout(fake: FakeProvider, http: HttpTransport, audio: Path) -> None:
    AssemblyFake(fake, [Reply(body=AAI_DONE)])
    fake.routes["POST /v2/upload"] = Reply(body={"upload_url": "https://x.test/u"}, delay_s=1.5)
    with pytest.raises(ProviderError) as caught:
        await assembly_call(fake, http, audio, total_s=0.2)
    assert caught.value.code == "provider_timeout"


async def test_assemblyai_failed_deletion_does_not_hide_the_result(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None, caplog: pytest.LogCaptureFixture
) -> None:
    AssemblyFake(fake, [Reply(body=AAI_DONE)])
    fake.routes["DELETE /v2/transcript/tr-1"] = Reply(500, {"error": f"{KEY} {PHRASE}"})
    with caplog.at_level(logging.DEBUG):
        result = await assembly_call(fake, http, audio)
    assert result.segments == AAI_SEGMENTS and result.diagnostics["remote_deleted"] is False
    assert any("deletion failed" in record.getMessage() for record in caplog.records)


# --- Property 12: cancellation without orphans (AssemblyAI, asynchronous provider) ---------------------


async def test_property_12_assemblyai_cancel_while_polling_deletes_the_remote_job_and_closes_streams(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    state = AssemblyFake(fake, [Reply(body={"id": "tr-1", "status": "processing"})])
    cancel = asyncio.Event()
    task = asyncio.create_task(assembly_call(fake, http, audio, cancel=cancel))
    await wait_polled(fake)
    started = time.monotonic()
    cancel.set()
    with pytest.raises(AdapterCancelled):
        await task
    await fake.wait_open(0, timeout_s=2.0)
    assert state.deleted == ["tr-1"] and time.monotonic() - started < 2.0


async def test_property_12_assemblyai_task_cancellation_still_deletes(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None
) -> None:
    state = AssemblyFake(fake, [Reply(body={"id": "tr-1", "status": "processing"})])
    task = asyncio.create_task(assembly_call(fake, http, audio))
    await wait_polled(fake)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert state.deleted == ["tr-1"]
    await fake.wait_open(0, timeout_s=2.0)


@pytest.mark.parametrize("hung", ["POST /v2/upload", "POST /v2/transcript", "GET /v2/transcript/tr-1"])
async def test_property_12_assemblyai_cancel_at_any_call_leaves_no_open_stream(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None, hung: str
) -> None:
    state = AssemblyFake(fake, [Reply(body=AAI_DONE)])
    fake.routes[hung] = Reply(hang=True)
    cancel = asyncio.Event()
    task = asyncio.create_task(assembly_call(fake, http, audio, cancel=cancel))
    deadline = time.monotonic() + 2
    while not fake.calls(*hung.split(" ", 1)):  # the call that hangs has reached the provider
        assert time.monotonic() < deadline
        await asyncio.sleep(0.005)
    await fake.wait_open(1)
    cancel.set()
    with pytest.raises(AdapterCancelled):
        await task
    await fake.wait_open(0, timeout_s=2.0)
    # Remote work exists only once the job id is known; then it is deleted.
    assert state.deleted == (["tr-1"] if hung.startswith("GET") else [])
    if hung == "POST /v2/upload":
        assert fake.calls("POST", "/v2/transcript") == []


async def test_property_12_assemblyai_already_cancelled_sends_nothing(
    fake: FakeProvider, http: HttpTransport, audio: Path
) -> None:
    cancel = asyncio.Event()
    cancel.set()
    with pytest.raises(AdapterCancelled):
        await assembly_call(fake, http, audio, cancel=cancel)
    assert fake.seen == []


# --- Deepgram ----------------------------------------------------------------------------------------

DG_DONE: dict[str, Any] = {
    "metadata": {"request_id": "r-1", "duration": 4.5, "channels": 1, "diarize_info": {"arch": "v2"}},
    "results": {
        "channels": [
            {
                "alternatives": [
                    {
                        "transcript": f"hola {PHRASE}",
                        "confidence": 0.99,
                        "words": [
                            {"word": "hola", "start": 0.2, "end": 0.64, "speaker": 0, "speaker_confidence": 0.9},
                            {"word": "frase", "start": 2.1, "end": 2.5, "speaker": 1},
                            {"word": "confidencial", "start": 2.6, "end": 3.4, "speaker": 1},
                            {"word": "gracias", "start": 3.5, "end": 3.9, "speaker": 0},
                        ],
                    }
                ]
            }
        ]
    },
}
DG_SEGMENTS = (Seg("0", 200, 640), Seg("1", 2100, 3400), Seg("0", 3500, 3900))


async def deepgram_call(fake: FakeProvider, http: HttpTransport, audio: Path, **kwargs: Any) -> DiarResult:
    route = make_route(fake, "deepgram", model=kwargs.pop("model", "nova-3"), total_s=kwargs.pop("total_s", 5.0))
    cancel = kwargs.pop("cancel", None) or asyncio.Event()
    return await diar_deepgram.diarize(
        http, audio, route=route, secret=SECRET, cancel=cancel, allow_local=True, **kwargs
    )


async def test_deepgram_sends_raw_audio_with_diarize_model_and_returns_one_segment_per_run(
    fake: FakeProvider, http: HttpTransport, audio: Path
) -> None:
    fake.routes["POST /v1/listen"] = Reply(body=DG_DONE)
    result = await deepgram_call(fake, http, audio, language="es", audio_ms=4500)
    (request,) = fake.seen
    assert request.headers["authorization"] == f"Token {KEY}" and request.headers["content-type"] == "audio/ogg"
    assert request.body == audio.read_bytes()
    assert request.query == {"model": ["nova-3"], "diarize_model": ["latest"], "language": ["es"]}
    assert "diarize" not in request.query  # setting both parameters is rejected by the provider
    assert result.segments == DG_SEGMENTS and result.speaker_count == 2 and result.audio_ms == 4500


async def test_deepgram_default_language_is_detection_and_duration_comes_from_the_provider(
    fake: FakeProvider, http: HttpTransport, audio: Path
) -> None:
    fake.routes["POST /v1/listen"] = Reply(body=DG_DONE)
    result = await deepgram_call(fake, http, audio, diarize_model="v2")
    query = fake.seen[0].query
    assert query["detect_language"] == ["true"] and "language" not in query and query["diarize_model"] == ["v2"]
    assert result.audio_ms == 4500


async def test_deepgram_refuses_unsafe_parameters_before_any_call(
    fake: FakeProvider, http: HttpTransport, audio: Path
) -> None:
    for kwargs in ({"diarize_model": "v2&diarize=true"}, {"media_type": "text/plain"}, {"language": "xx yy"}):
        with pytest.raises(ProviderError) as caught:
            await deepgram_call(fake, http, audio, **kwargs)
        assert caught.value.code == "provider_bad_request"
    assert fake.seen == []


async def test_deepgram_words_without_a_speaker_are_invalid_output(
    fake: FakeProvider, http: HttpTransport, audio: Path
) -> None:
    bare = json.loads(json.dumps(DG_DONE))
    for word in bare["results"]["channels"][0]["alternatives"][0]["words"]:
        del word["speaker"]  # what a self-hosted v2-only deployment answers to diarize=true
    fake.routes["POST /v1/listen"] = Reply(body=bare)
    with pytest.raises(ProviderError) as caught:
        await deepgram_call(fake, http, audio)
    assert (caught.value.code, caught.value.reason) == ("provider_invalid_output", "no_speaker_labels")


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
    result = await deepgram_call(fake, http, audio)
    assert (result.segments, result.speaker_count, result.audio_ms) == ((), 0, 3000)


@pytest.mark.parametrize("speaker", [-1, 1.5, "0 1", True, [0], {"s": 0}])
async def test_deepgram_refuses_a_speaker_that_is_not_an_index(
    fake: FakeProvider, http: HttpTransport, audio: Path, speaker: object
) -> None:
    broken = json.loads(json.dumps(DG_DONE))
    broken["results"]["channels"][0]["alternatives"][0]["words"][0]["speaker"] = speaker
    fake.routes["POST /v1/listen"] = Reply(body=broken)
    with pytest.raises(ProviderError) as caught:
        await deepgram_call(fake, http, audio)
    assert (caught.value.code, caught.value.reason) == ("provider_invalid_output", "bad_speaker_label")


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


async def test_property_12_deepgram_timeout_and_cancel_leave_no_open_stream(
    fake: FakeProvider, http: HttpTransport, audio: Path
) -> None:
    fake.routes["POST /v1/listen"] = Reply(body=DG_DONE, delay_s=1.5)
    with pytest.raises(ProviderError) as caught:
        await deepgram_call(fake, http, audio, total_s=0.2)
    assert caught.value.code == "provider_timeout"
    await fake.wait_open(0, timeout_s=2.0)
    fake.routes["POST /v1/listen"] = Reply(hang=True)
    cancel = asyncio.Event()
    task = asyncio.create_task(deepgram_call(fake, http, audio, cancel=cancel))
    await fake.wait_open(1)
    started = time.monotonic()
    cancel.set()
    with pytest.raises(AdapterCancelled):
        await task
    await fake.wait_open(0, timeout_s=2.0)
    assert time.monotonic() - started < 2.0


async def test_property_12_deepgram_already_cancelled_sends_nothing(
    fake: FakeProvider, http: HttpTransport, audio: Path
) -> None:
    cancel = asyncio.Event()
    cancel.set()
    with pytest.raises(AdapterCancelled):
        await deepgram_call(fake, http, audio, cancel=cancel)
    assert fake.seen == []


async def test_deepgram_works_with_the_real_safe_http_transport(fake: FakeProvider, audio: Path) -> None:
    fake.routes["POST /v1/listen"] = Reply(body=DG_DONE)
    transport = SafeHttp()
    assert (await deepgram_call(fake, transport, audio)).segments == DG_SEGMENTS
    with pytest.raises(ProviderError) as caught:  # the address policy still refuses loopback without allow_local
        await diar_deepgram.diarize(
            transport,
            audio,
            route=make_route(fake, "deepgram"),
            secret=SECRET,
            cancel=asyncio.Event(),
            allow_local=False,
        )
    assert caught.value.code == "provider_bad_request"


# --- Property 8: exact union of consecutive words per label --------------------------------------------

labels = st.sampled_from(["A", "B", "C", "0", "1", "speaker_2"])
runs = st.lists(st.tuples(labels, st.integers(1, 500), st.integers(0, 900)), min_size=0, max_size=25)


def timeline(raw: list[tuple[str, int, int]]) -> list[tuple[str, int, int]]:
    """Words one after the other as (label, start, end): strictly increasing starts, zero-length words included."""
    out: list[tuple[str, int, int]] = []
    cursor = 0
    for label, gap, duration in raw:
        start = cursor + gap
        out.append((label, start, start + duration))
        cursor = start + duration
    return out


def dg_index(label: str) -> int:
    """A Deepgram speaker index for a test label (several labels may share one index)."""
    return int(label[-1]) if label[-1].isdigit() else ord(label[-1]) % 7


def expected_segments(words: list[tuple[str, int, int]]) -> list[tuple[str, int, int]]:
    return [
        (label, group[0][1], group[-1][2])
        for label, items in itertools.groupby(words, key=lambda w: w[0])
        for group in [list(items)]
    ]


@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
@given(raw=runs, order=st.randoms(use_true_random=False))
def test_property_8_segments_cover_exactly_the_consecutive_words_of_each_label(
    raw: list[tuple[str, int, int]], order: Any
) -> None:
    words = timeline(raw)
    shuffled = list(words)
    order.shuffle(shuffled)  # the provider order does not matter, time order does
    segments = union_runs(LabeledWord(label, s, e) for label, s, e in shuffled)
    assert [(s.raw_label, s.start_ms, s.end_ms) for s in segments] == expected_segments(words)  # no duration filter
    result = build_result([LabeledWord(label, s, e) for label, s, e in words], has_speech=bool(words), audio_ms=None)
    assert result.speaker_count == len({label for label, _s, _e in words}) == len({s.raw_label for s in segments})


@settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
@given(raw=runs, texts=st.lists(st.text(min_size=1, max_size=12), min_size=25, max_size=25))
def test_property_8_both_adapters_produce_the_union_and_no_text(
    raw: list[tuple[str, int, int]], texts: list[str]
) -> None:
    words = timeline(raw)
    sentinel = "SENTINEL-" + "-".join(texts)
    aai = {
        "words": [
            {"text": f"{sentinel}-{i}", "speaker": label, "start": s, "end": e} for i, (label, s, e) in enumerate(words)
        ],
        "text": sentinel if words else "",
    }
    dg = {
        "results": {"channels": [{"alternatives": [{
            "transcript": sentinel if words else "",
            "words": [{"word": f"{sentinel}-{i}", "speaker": dg_index(label), "start": s / 1000, "end": e / 1000}
                      for i, (label, s, e) in enumerate(words)],
        }]}]}
    }  # fmt: skip
    first = diar_assemblyai.parse_completed(aai, audio_ms=None)
    assert [(s.raw_label, s.start_ms, s.end_ms) for s in first.segments] == expected_segments(words)
    assert first.speaker_count == len({label for label, _s, _e in words})
    second = diar_deepgram.parse_listen(dg, audio_ms=None)
    labelled = [(str(dg_index(label)), s, e) for label, s, e in words]
    assert [(s.raw_label, s.start_ms, s.end_ms) for s in second.segments] == expected_segments(labelled)
    assert "SENTINEL" not in repr(first) + repr(second)


def test_property_8_a_single_zero_length_word_is_a_segment() -> None:
    result = build_result([LabeledWord("A", 700, 700)], has_speech=True, audio_ms=None)
    assert result.segments == (Seg("A", 700, 700),) and result.speaker_count == 1


def test_provider_times_are_repaired_never_invented() -> None:
    result = build_result(
        [LabeledWord("A", -50, 100), LabeledWord("B", 900, 800), LabeledWord("B", 950, 5000)],
        has_speech=True,
        audio_ms=1000,
    )
    assert result.segments == (Seg("A", 0, 100), Seg("B", 900, 1000))
    assert result.diagnostics["timing_repaired"] == 3


def test_safe_label_accepts_only_short_codes() -> None:
    assert [safe_label(v) for v in ("A", "speaker_1", 0, 12, None)] == ["A", "speaker_1", "0", "12", None]


def test_speaker_segment_payload_is_the_gateway_shape() -> None:
    assert Seg("A", 1, 2).to_payload() == {"speaker": "A", "start_ms": 1, "end_ms": 2}


# --- merge_parts: offsets applied only here, labels kept distinct per part --------------------------------


def part(*segments: tuple[str, int, int], audio_ms: int | None = None, deleted: bool | None = None) -> DiarResult:
    diagnostics: dict[str, object] = {} if deleted is None else {"remote_deleted": deleted}
    return DiarResult(
        tuple(Seg(label, s, e) for label, s, e in segments),
        len({label for label, _s, _e in segments}),
        audio_ms,
        diagnostics,
    )


def test_adapters_report_times_on_the_part_clock_without_an_offset() -> None:
    second_part = diar_assemblyai.parse_completed(AAI_DONE, audio_ms=1_000_000)
    assert second_part.segments[0].start_ms == 200  # the offset is added by merge_parts only


def test_merge_parts_applies_offsets_and_keeps_labels_distinct_per_part() -> None:
    merged = merge_parts(
        [part(("A", 100, 400), ("B", 500, 900), audio_ms=1000), part(("A", 50, 300), audio_ms=800)], [0, 1000]
    )
    assert merged.segments == (Seg("p1.A", 100, 400), Seg("p1.B", 500, 900), Seg("p2.A", 1050, 1300))
    assert merged.speaker_count == 3 and merged.audio_ms == 1800
    assert merged.diagnostics["label_policy"] == "per_part"
    assert merged.diagnostics["speaker_count_per_part"] == [2, 1] and merged.diagnostics["parts"] == 2


def test_merge_parts_one_part_keeps_the_provider_labels() -> None:
    merged = merge_parts([part(("A", 5, 9), ("B", 10, 20), audio_ms=30)], [0])
    assert merged.segments == (Seg("A", 5, 9), Seg("B", 10, 20)) and merged.diagnostics["label_policy"] == "provider"


def test_merge_parts_orders_parts_by_offset_and_numbers_them_in_that_order() -> None:
    merged = merge_parts([part(("A", 0, 100)), part(("A", 0, 100))], [5000, 0])
    assert [(s.raw_label, s.start_ms) for s in merged.segments] == [("p1.A", 0), ("p2.A", 5000)]


def test_merge_parts_does_not_trim_overlap_between_different_speakers() -> None:
    merged = merge_parts([part(("A", 0, 600), ("B", 450, 900))], [0])
    assert [(s.raw_label, s.start_ms, s.end_ms) for s in merged.segments] == [("A", 0, 600), ("B", 450, 900)]


def test_merge_parts_links_identities_only_when_the_caller_says_so() -> None:
    merged = merge_parts(
        [part(("A", 0, 100), ("B", 200, 300)), part(("B", 0, 100), ("A", 200, 300))],
        [0, 1000],
        identity={(0, "A"): "alice", (1, "B"): "alice"},
    )
    assert [s.raw_label for s in merged.segments] == ["alice", "p1.B", "alice", "p2.A"]
    assert merged.speaker_count == 3 and merged.diagnostics["label_policy"] == "per_part_with_identity"


def test_merge_parts_rejects_inconsistent_arguments() -> None:
    for results, offsets in (([], []), ([part(("A", 0, 1))], [0, 1]), ([part(("A", 0, 1))], [-1])):
        with pytest.raises(ValueError, match="invalid_parts"):
            merge_parts(results, offsets)
    with pytest.raises(ValueError, match="invalid_identity"):
        merge_parts([part(("A", 0, 1))], [0], identity={(0, "A"): "not a label!"})


def test_merge_parts_reports_remote_deletion_and_repairs_across_parts() -> None:
    merged = merge_parts([part(("A", 0, 1), deleted=True), part(("A", 0, 1), deleted=False)], [0, 10])
    assert merged.diagnostics["remote_deleted"] is False and merged.diagnostics["timing_repaired"] == 0


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(raws=st.lists(runs, min_size=1, max_size=4), gaps=st.lists(st.integers(0, 5000), min_size=4, max_size=4))
def test_property_merged_segments_shift_exactly_by_their_offset(
    raws: list[list[tuple[str, int, int]]], gaps: list[int]
) -> None:
    offsets = list(itertools.accumulate(gaps[: len(raws)]))
    parts = [
        build_result([LabeledWord(label, s, e) for label, s, e in timeline(raw)], has_speech=bool(raw), audio_ms=None)
        for raw in raws
    ]
    merged = merge_parts(parts, offsets)
    expected = sorted(
        (f"p{i + 1}.{seg.raw_label}" if len(parts) > 1 else seg.raw_label, seg.start_ms + off, seg.end_ms + off)
        for i, (off, result) in enumerate(sorted(zip(offsets, parts, strict=True), key=lambda p: p[0]))
        for seg in result.segments
    )
    assert sorted((s.raw_label, s.start_ms, s.end_ms) for s in merged.segments) == expected
    assert merged.speaker_count == len({label for label, _s, _e in expected})


# --- Property 4: no key, header or provider text in outputs, logs or exceptions ------------------------


def _all_text(error: BaseException) -> str:
    return "".join(traceback.format_exception(error)) + repr(error) + str(error) + repr(vars(error))


@pytest.mark.parametrize("transport", ["assemblyai", "deepgram"])
@pytest.mark.parametrize("failure", ["http_error", "bad_json", "no_labels", "bad_label", "success"])
async def test_nothing_sensitive_reaches_results_logs_or_exceptions(
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
    aai = json.loads(json.dumps(AAI_DONE))
    dg = json.loads(json.dumps(DG_DONE))
    if failure == "no_labels":
        for word in aai["words"] + dg["results"]["channels"][0]["alternatives"][0]["words"]:
            word.pop("speaker")
        aai["utterances"] = None
    if failure == "bad_label":
        aai["words"][0]["speaker"] = f"{KEY} {PHRASE}"
        dg["results"]["channels"][0]["alternatives"][0]["words"][0]["speaker"] = f"{KEY} {PHRASE}"
    run: Callable[[], Awaitable[DiarResult]]
    if transport == "deepgram":
        fake.routes["POST /v1/listen"] = (
            Reply(500, echo) if failure == "http_error"
            else Reply(raw=f"{KEY} {PHRASE}".encode()) if failure == "bad_json" else Reply(body=dg)
        )  # fmt: skip
        run = lambda: deepgram_call(fake, http, audio)  # noqa: E731
    else:
        AssemblyFake(fake, [Reply(body=aai)])
        if failure == "http_error":
            fake.routes["GET /v2/transcript/tr-1"] = [Reply(401, echo)]
        elif failure == "bad_json":
            fake.routes["GET /v2/transcript/tr-1"] = [Reply(raw=f"{KEY} {PHRASE}".encode())]
        run = lambda: assembly_call(fake, http, audio)  # noqa: E731
    caplog.set_level(logging.DEBUG)
    texts: list[str] = []
    try:
        result = await run()
        texts.append(repr(result) + repr(result.diagnostics) + repr([s.to_payload() for s in result.segments]))
    except ProviderError as error:
        texts.append(_all_text(error))
        assert failure != "success"
    else:
        assert failure == "success"
    texts.extend(record.getMessage() + repr(record.args) for record in caplog.records)
    joined = "\n".join(texts)
    for forbidden in (KEY, PHRASE, "confidencial", "frase", "hola", "gracias", "Bearer"):
        assert forbidden not in joined


async def test_a_failed_deletion_log_carries_only_a_class(
    fake: FakeProvider, http: HttpTransport, audio: Path, fast_polling: None, caplog: pytest.LogCaptureFixture
) -> None:
    AssemblyFake(fake, [Reply(body=AAI_DONE)])
    fake.routes["DELETE /v2/transcript/tr-1"] = Reply(500, {"error": f"{KEY} {PHRASE}"})
    caplog.set_level(logging.DEBUG)
    await assembly_call(fake, http, audio)
    assert [r.getMessage() for r in caplog.records if r.name.startswith("sauri.")] == [
        "assemblyai transcript deletion failed (class=provider_unavailable)"
    ]
