"""U4.3 (#1117): upload -> external transcription -> word attribution -> meeting completed.

Real parts: the worker, the ASR gateway (``native_main``) served over HTTP on a random loopback port, the
route header, the host secret store (private files), audio preparation (real ffmpeg) and the adapter. Fake
parts: the provider (AssemblyAI-shaped, loopback), whisper (a script that writes a fixed answer), object
storage and the diarization engine. No real provider, key or audio is involved, and Spanish quality is
NO VERIFICADO until the owner's run (U10).

Runs on SQLite and, with ``SAURI_QA_POSTGRES_URL`` (a disposable ``sauri_qa`` database), on PostgreSQL.
"""

from __future__ import annotations

import asyncio
import os
import stat
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.diarization.diarization_engine import DiarizationResult, SpeakerSegment
from app.diarization.worker import _process_diarization
from app.infra.database import Base
from app.infra.engine_slot import engine_slot
from app.infra.models import (
    Meeting,
    MeetingProcessingClaim,
    SessionRecording,
    SpeechTurn,
    SummaryTemplate,
    Transcript,
    TranscriptWord,
    User,
    WordSpeakerAssignment,
)
from app.transcription.worker import _process_transcription
from tests.external_asr_support import (
    OWNER,
    PROVIDER_KEY,
    FakeAssemblyAI,
    Served,
    add_provider,
    choose,
    consent,
    load_native_asr,
    serve,
    write_tone_wav,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine-common"))
from sauri_engine_common.secrets import FileSecretStore, SecretRecord  # noqa: E402

Factory = async_sessionmaker[AsyncSession]
AUDIO_REF = "synthetic/recording.wav"
SECRET_REF = "sauri/owner/provider"
WORDS = [("Hola", 100, 400), ("equipo", 450, 900), ("gracias.", 1200, 1500)]
FAKE_WHISPER = """#!{python}
import json, sys
argv = sys.argv
with open({log!r}, 'a') as log:
    log.write('run\\n')
document = {{"result": {{"language": "es"}}, "transcription": [{{
    "text": " hola local", "offsets": {{"from": 250, "to": 1500}},
    "tokens": [{{"text": " hola", "id": 1, "p": 0.9, "offsets": {{"from": 300, "to": 700}}}},
               {{"text": " local", "id": 2, "p": 0.8, "offsets": {{"from": 800, "to": 1400}}}}],
}}]}}
with open(argv[argv.index('-of') + 1] + '.json', 'w') as out:
    json.dump(document, out)
"""


@pytest.fixture(params=["sqlite", "postgres"])
async def factory(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Factory]:
    if request.param == "sqlite":
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'u43.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
        await engine.dispose()
        return
    raw = os.environ.get("SAURI_QA_POSTGRES_URL")
    if not raw:
        pytest.skip("SAURI_QA_POSTGRES_URL required for the PostgreSQL run")
    url = make_url(raw)
    assert url.drivername == "postgresql+asyncpg" and "sauri_qa" in (url.database or "")
    schema = f"sauri_qa_u43_{uuid4().hex}"
    admin = create_async_engine(url)
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


@dataclass
class World:
    factory: Factory
    fake: FakeAssemblyAI
    served: Served
    native: ModuleType
    whisper_log: Path
    store: FileSecretStore

    @property
    def whisper_runs(self) -> int:
        return len(self.whisper_log.read_text().splitlines()) if self.whisper_log.exists() else 0

    async def link_provider(self, *, fallback: bool = True, consented: bool = True, model: str = "universal-2") -> str:
        provider = await add_provider(self.factory, kind="assemblyai", secret_ref=SECRET_REF, base_url=self.served.url)
        self.store.put(SECRET_REF, SecretRecord(key=PROVIDER_KEY, origin=self.served.url))
        await choose(self.factory, provider, model, fallback=fallback)
        if consented:
            await consent(self.factory, provider)
        return provider


@pytest.fixture
async def world(
    factory: Factory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[World]:
    fake = FakeAssemblyAI(words_for=lambda n: list(WORDS))
    native = load_native_asr("native_asr_engine_pipeline")
    store = FileSecretStore(tmp_path / "secrets")
    token = tmp_path / "engine_token"
    token.write_text("synthetic-token")
    capability_key = tmp_path / "capability_key"
    capability_key.write_bytes(b"synthetic-secret")
    whisper_log = tmp_path / "whisper.log"
    whisper = tmp_path / "whisper-cli"
    whisper.write_text(FAKE_WHISPER.format(python=sys.executable, log=str(whisper_log)))
    whisper.chmod(whisper.stat().st_mode | stat.S_IXUSR)

    monkeypatch.setenv("SAURI_ASR_VAD", "off")
    monkeypatch.setenv("SAURI_ASR_SUPPRESS_NST", "off")
    monkeypatch.setenv("SAURI_ASR_VOCABULARY_FILE", str(tmp_path / "no-vocabulary"))
    monkeypatch.setenv("SAURI_ASR_ALLOW_LOCAL_PROVIDERS", "1")
    # Isolate from a Parakeet install on the host: "no configuration" means Whisper is the local default.
    monkeypatch.setenv("SAURI_PARAKEET_HOME", str(tmp_path / "no-parakeet"))
    monkeypatch.setenv("SAURI_ENGINE_TOKEN_FILE", str(token))
    monkeypatch.setenv("SAURI_RECORDING_CAPABILITY_KEY_FILE", str(capability_key))
    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token)
    monkeypatch.setattr(native, "RECORDING_CAPABILITY_KEY_PATH", capability_key)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "synthetic/")
    monkeypatch.setattr(native, "MINIO_BUCKET", "synthetic-bucket")
    monkeypatch.setattr(native, "WHISPER_CLI", str(whisper))
    # The built-in Whisper model must be on disk for a Whisper request (the fake whisper-cli never reads it).
    model = tmp_path / "ggml-synthetic.bin"
    model.write_bytes(b"synthetic model")
    monkeypatch.setattr(native, "ASR_MODEL_PATH", model)
    monkeypatch.setattr(native, "secret_store", store)
    monkeypatch.setattr(native, "KeepAwake", nullcontext)
    monkeypatch.setattr(native.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(
        native, "s3_client", SimpleNamespace(get_object=lambda **kw: {"Body": BytesIO(b"synthetic audio")})
    )
    monkeypatch.setattr(
        native, "normalize_to_wav",
        lambda source, dest, **kw: SimpleNamespace(audio_ms=write_tone_wav(dest, 3.0), seconds=0.01),
    )

    @asynccontextmanager
    async def slot(engine: AsyncEngine, *, kind: str, timeout_s: float) -> AsyncIterator[None]:
        if engine.dialect.name == "sqlite":
            yield
        else:
            async with engine_slot(engine, kind=kind, poll_s=0.01, timeout_s=30.0):
                yield

    class Diarizer:
        async def diarize(self, *_: Any) -> DiarizationResult:
            return DiarizationResult(segments=[SpeakerSegment("A", 0, 600), SpeakerSegment("B", 600, 1600)],
                                     speaker_count=2)

        def capabilities(self) -> SimpleNamespace:
            return SimpleNamespace(is_local=True, supports_turns=True, provider_name="synthetic")

    monkeypatch.setattr("app.transcription.worker.engine_slot", slot)
    monkeypatch.setattr("app.diarization.worker.engine_slot", slot)
    monkeypatch.setattr("app.diarization.worker.create_diarization_engine", lambda: Diarizer())

    with serve(fake.app()) as provider, serve(native.app) as gateway:
        monkeypatch.setenv("ASR_LOCAL_URL", gateway.url)
        monkeypatch.delenv("ASR_PROVIDER", raising=False)
        yield World(factory, fake, provider, native, whisper_log, store)


async def seed(factory: Factory) -> dict[str, Any]:
    meeting, recording, template = (str(uuid4()) for _ in range(3))
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        session.add(User(id=OWNER, email="owner@example.test", name="Synthetic", password_hash="unused",
                         is_sales=True, created_at=now))
        session.add(
            Meeting(id=meeting, origin="upload", process_state="transcribing", created_by=OWNER, created_at=now)
        )
        await session.flush()
        session.add(SummaryTemplate(id=template, owner_user_id=OWNER, name="Default", instructions="Brief",
                                    version=1, created_at=now, updated_at=now))
        session.add(SessionRecording(id=recording, meeting_id=meeting, idempotency_key=recording,
                                     capture_origin="web_upload", audio_ref=AUDIO_REF, duration_seconds=3,
                                     interrupted=False, finished_at=now))
        session.add(MeetingProcessingClaim(meeting_id=meeting, generation=1))
        await session.flush()
        user = await session.get(User, OWNER)
        assert user is not None
        user.default_summary_template_id = template
    return {"meeting_id": meeting, "owner_id": OWNER, "recording_id": recording, "audio_ref": AUDIO_REF,
            "generation": 1, "job_id": str(uuid4())}


async def transcribe(factory: Factory, message: dict[str, Any]) -> AsyncMock:
    queue = AsyncMock()
    await _process_transcription(message, factory, queue)
    return queue


async def transcript_of(factory: Factory, meeting_id: str) -> Transcript | None:
    async with factory() as session:
        return await session.scalar(select(Transcript).where(Transcript.meeting_id == meeting_id))


async def meeting_of(factory: Factory, meeting_id: str) -> Meeting:
    async with factory() as session:
        meeting = await session.get(Meeting, meeting_id)
        assert meeting is not None
        return meeting


async def test_external_transcription_then_word_attribution_completes_the_meeting(world: World) -> None:
    """Properties 1-2 (a consented external route works) and the unit's done criterion."""
    message = await seed(world.factory)
    await world.link_provider()

    queue = await transcribe(world.factory, message)

    transcript = await transcript_of(world.factory, message["meeting_id"])
    assert transcript is not None
    assert (transcript.engine_name, transcript.engine_model) == ("assemblyai", "universal-2")
    assert transcript.engine_external is True and transcript.engine_fallback_reason is None
    assert transcript.provider == "cloud" and transcript.language == "es"
    assert (await meeting_of(world.factory, message["meeting_id"])).process_state == "completed"
    assert world.whisper_runs == 0  # nothing ran locally
    assert {s.authorization for s in world.fake.seen} == {PROVIDER_KEY}
    assert world.fake.deleted == ["job-0"]
    queue.publish.assert_awaited_once()
    topic, diarization_message = queue.publish.await_args.args
    assert topic == "diarize"

    await _process_diarization(dict(diarization_message), world.factory)
    async with world.factory() as session:
        words = list(await session.scalars(select(TranscriptWord).order_by(TranscriptWord.sequence)))
        assert [(w.text, w.start_ms, w.end_ms) for w in words] == WORDS
        assigned = list(
            await session.scalars(select(WordSpeakerAssignment).join(TranscriptWord).order_by(TranscriptWord.sequence))
        )
        assert [a.state for a in assigned] == ["assigned", "assigned", "assigned"]
        assert len({a.speaker_id for a in assigned}) == 2  # "Hola" is speaker A, the rest speaker B
        assert await session.scalar(select(func.count()).select_from(SpeechTurn)) == 1
    assert (await meeting_of(world.factory, message["meeting_id"])).process_state == "completed"


async def test_property_1_without_configuration_the_local_engine_answers_and_nothing_goes_out(world: World) -> None:
    message = await seed(world.factory)
    await transcribe(world.factory, message)
    transcript = await transcript_of(world.factory, message["meeting_id"])
    assert transcript is not None
    assert (transcript.engine_name, transcript.engine_external) == ("whisper.cpp", False)
    assert transcript.provider == "local" and transcript.engine_fallback_reason is None
    assert world.whisper_runs == 1 and world.fake.seen == []


@pytest.mark.parametrize("failure", [{"upload_status": 503}, {"upload_status": 429}, {"create_status": 500}])
async def test_transient_failure_with_fallback_uses_the_local_engine_and_records_the_real_provenance(
    world: World, failure: dict[str, int]
) -> None:
    for name, value in failure.items():
        setattr(world.fake, name, value)
    message = await seed(world.factory)
    await world.link_provider(fallback=True)

    await transcribe(world.factory, message)

    transcript = await transcript_of(world.factory, message["meeting_id"])
    assert transcript is not None
    assert (transcript.engine_name, transcript.engine_model) == ("whisper.cpp", world.native.MODEL_ID)
    assert transcript.engine_external is False and transcript.provider == "local"
    assert transcript.engine_fallback_reason in {"provider_unavailable", "provider_rate_limited"}
    assert world.whisper_runs == 1 and world.fake.calls("POST", "/v2/upload")
    assert (await meeting_of(world.factory, message["meeting_id"])).process_state == "completed"
    async with world.factory() as session:
        assert [w.text for w in await session.scalars(select(TranscriptWord).order_by(TranscriptWord.sequence))] == [
            " hola", " local"]


async def test_transient_failure_without_fallback_fails_the_meeting_with_the_class(world: World) -> None:
    world.fake.upload_status = 503
    message = await seed(world.factory)
    await world.link_provider(fallback=False)
    await transcribe(world.factory, message)
    meeting = await meeting_of(world.factory, message["meeting_id"])
    assert (meeting.process_state, meeting.failure_cause) == ("failed", "provider_unavailable")
    assert await transcript_of(world.factory, message["meeting_id"]) is None and world.whisper_runs == 0


async def test_property_14_user_action_failures_never_change_the_engine(world: World) -> None:
    world.fake.upload_status = 401
    message = await seed(world.factory)
    await world.link_provider(fallback=True)
    await transcribe(world.factory, message)
    meeting = await meeting_of(world.factory, message["meeting_id"])
    assert (meeting.process_state, meeting.failure_cause) == ("failed", "provider_auth")
    assert world.whisper_runs == 0 and len(world.fake.calls("POST", "/v2/upload")) == 1


async def test_property_2_without_consent_nothing_is_sent_and_the_local_engine_is_not_used(world: World) -> None:
    message = await seed(world.factory)
    await world.link_provider(consented=False)
    await transcribe(world.factory, message)
    meeting = await meeting_of(world.factory, message["meeting_id"])
    assert (meeting.process_state, meeting.failure_cause) == ("failed", "consent_missing")
    assert world.fake.seen == [] and world.whisper_runs == 0
    assert await transcript_of(world.factory, message["meeting_id"]) is None


async def test_property_15_redelivery_with_another_engine_does_not_duplicate_the_transcript(world: World) -> None:
    message = await seed(world.factory)
    await transcribe(world.factory, message)  # local
    await world.link_provider()  # the owner switches to the provider
    await transcribe(world.factory, message)  # the same delivery arrives again: the finished stage is dropped
    async with world.factory() as session:
        assert await session.scalar(select(func.count()).select_from(Transcript)) == 1
        assert await session.scalar(select(func.count()).select_from(TranscriptWord)) == 2
    assert world.fake.seen == [] and world.whisper_runs == 1


async def test_a_change_applies_to_the_next_meeting_without_restarting_anything(world: World) -> None:
    first, second = await seed(world.factory), None
    await transcribe(world.factory, first)
    local = await transcript_of(world.factory, first["meeting_id"])
    assert local is not None and local.engine_external is False
    async with world.factory() as session, session.begin():  # a second meeting of the same owner
        meeting, recording = str(uuid4()), str(uuid4())
        now = datetime.now(UTC)
        session.add(
            Meeting(id=meeting, origin="upload", process_state="transcribing", created_by=OWNER, created_at=now)
        )
        await session.flush()
        session.add(SessionRecording(id=recording, meeting_id=meeting, idempotency_key=recording,
                                     capture_origin="web_upload", audio_ref=AUDIO_REF, duration_seconds=3,
                                     interrupted=False, finished_at=now))
        session.add(MeetingProcessingClaim(meeting_id=meeting, generation=1))
        second = {**first, "meeting_id": meeting, "recording_id": recording, "job_id": str(uuid4())}
    await world.link_provider()
    await transcribe(world.factory, second)
    external = await transcript_of(world.factory, second["meeting_id"])
    assert external is not None and (external.engine_name, external.engine_external) == ("assemblyai", True)


async def test_the_worker_going_away_cancels_the_provider_call_and_deletes_the_remote_job(
    world: World, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    world.fake.hang = True
    monkeypatch.setattr("app.transcription.worker.ENGINE_CALL_TIMEOUT_S", 1.5)
    message = await seed(world.factory)
    await world.link_provider(fallback=False)
    await transcribe(world.factory, message)
    meeting = await meeting_of(world.factory, message["meeting_id"])
    assert (meeting.process_state, meeting.failure_cause) == ("failed", "engine_timeout")
    deadline = time.monotonic() + 10  # the gateway notices the closed connection within its watch interval
    while not world.fake.deleted and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
    assert world.fake.deleted == ["job-0"]
    assert PROVIDER_KEY not in caplog.text

