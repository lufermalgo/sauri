"""U5.2 (#1138): local transcript + external speakers -> word attribution -> turns.

Real parts: the diarization worker, the diarization gateway (``native_main``) served over HTTP on a random
loopback port, the route header, the host secret store (private files), audio preparation (real ffmpeg) and
the Deepgram adapter. Fake parts: the provider (Deepgram-shaped, loopback), Senko (a counting stand-in),
object storage and the transcription engine (a local engine that answers fixed words). No real provider, key
or audio is involved, and Spanish speaker quality is NO VERIFICADO until the owner's run (U10).

Runs on SQLite and, with ``SAURI_QA_POSTGRES_URL`` (a disposable ``sauri_qa`` database), on PostgreSQL.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.diarization.repository import DiarizationRepository
from app.diarization.worker import _process_diarization
from app.infra.database import Base
from app.infra.engine_slot import engine_slot
from app.infra.models import (
    Diarization,
    Meeting,
    MeetingProcessingClaim,
    SessionRecording,
    Speaker,
    SpeakerAssignment,
    SpeechTurn,
    SummaryTemplate,
    Transcript,
    TranscriptWord,
    User,
    WordSpeakerAssignment,
)
from app.transcription.asr_engine import (
    ASRCapabilities,
    EngineInfo,
    TranscriptionResult,
    TranscriptionSegment,
    TranscriptionWord,
)
from app.transcription.worker import _process_transcription
from tests.external_asr_support import OWNER, PROVIDER_KEY, Served, add_provider, choose, consent, serve, write_tone_wav
from tests.external_diar_support import FakeDeepgram, load_native_diar

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine-common"))
from sauri_engine_common.external.errors import ProviderError  # noqa: E402
from sauri_engine_common.secrets import FileSecretStore, SecretRecord  # noqa: E402

Factory = async_sessionmaker[AsyncSession]
AUDIO_REF = "synthetic/recording.wav"
SECRET_REF = "sauri/owner/speakers"
WORDS = [("Hola", 100, 400), ("equipo", 450, 900), ("gracias.", 1200, 1500)]
# Provider answer (seconds on the part clock): speaker 0 says the first word, speaker 1 the rest.
PROVIDER_WORDS = [(0, "Hola", 0.1, 0.4), (1, "equipo", 0.45, 0.9), (1, "gracias.", 1.2, 1.5)]
SENKO_SEGMENTS = [
    {"start": 0.0, "end": 0.6, "speaker": "SPEAKER_00"},
    {"start": 0.6, "end": 1.6, "speaker": "SPEAKER_01"},
]


@pytest.fixture(params=["sqlite", "postgres"])
async def factory(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Factory]:
    if request.param == "sqlite":
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'u52.db'}")
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
    schema = f"sauri_qa_u52_{uuid4().hex}"
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


class LocalAsr:
    """The transcription engine of this run: local, fixed words (the unit under test is the speakers)."""

    async def transcribe(self, *_: Any) -> TranscriptionResult:
        return TranscriptionResult(
            segments=[TranscriptionSegment("Hola equipo gracias.", 100, 1500)],
            words=[TranscriptionWord(text, start, end, 0.9) for text, start, end in WORDS],
            language="es",
            engine=EngineInfo("whisper.cpp", "synthetic-model", "metal"),
            supports_turns=True,
        )

    def capabilities(self) -> ASRCapabilities:
        return ASRCapabilities(supports_turns=True, is_local=True)


@dataclass
class World:
    factory: Factory
    provider: FakeDeepgram
    served: Served
    native: ModuleType
    senko_runs: list[str]
    store: FileSecretStore

    async def link_provider(
        self, *, fallback: bool = True, consented: bool = True, kind: str = "deepgram", model: str = "nova-3"
    ) -> str:
        provider = await add_provider(
            self.factory, kind=kind, secret_ref=SECRET_REF, base_url=self.served.url
        )
        self.store.put(SECRET_REF, SecretRecord(key=PROVIDER_KEY, origin=self.served.url))
        await choose(self.factory, provider, model, capability="diarization", fallback=fallback)
        if consented:
            await consent(self.factory, provider, capability="diarization")
        return provider


@pytest.fixture
async def world(factory: Factory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AsyncIterator[World]:
    fake = FakeDeepgram(words_for=lambda n: list(PROVIDER_WORDS))
    native = load_native_diar("native_diar_engine_pipeline")
    store = FileSecretStore(tmp_path / "secrets")
    token = tmp_path / "engine_token"
    token.write_text("synthetic-token")
    capability_key = tmp_path / "capability_key"
    capability_key.write_bytes(b"synthetic-secret")
    senko_runs: list[str] = []

    class SyntheticS3:
        def download_file(self, bucket: str, audio_ref: str, path: str) -> None:
            Path(path).write_bytes(b"synthetic audio")

    def senko(*, wav_path: str, accurate: bool, generate_colors: bool) -> dict[str, Any]:
        senko_runs.append(wav_path)
        return {"raw_segments": list(SENKO_SEGMENTS), "merged_segments": []}

    monkeypatch.setenv("SAURI_DIAR_ALLOW_LOCAL_PROVIDERS", "1")
    monkeypatch.setenv("SAURI_ENGINE_TOKEN_FILE", str(token))
    monkeypatch.setenv("SAURI_RECORDING_CAPABILITY_KEY_FILE", str(capability_key))
    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token)
    monkeypatch.setattr(native, "RECORDING_CAPABILITY_KEY_PATH", capability_key)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "synthetic/")
    monkeypatch.setattr(native, "MINIO_BUCKET", "synthetic-bucket")
    monkeypatch.setattr(native, "secret_store", store)
    monkeypatch.setattr(native, "KeepAwake", nullcontext)
    monkeypatch.setattr(native.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(native, "s3_client", SyntheticS3())
    monkeypatch.setattr(native, "diarization_pipeline", SimpleNamespace(diarize=senko))
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

    monkeypatch.setattr("app.transcription.worker.engine_slot", slot)
    monkeypatch.setattr("app.diarization.worker.engine_slot", slot)
    monkeypatch.setattr("app.transcription.worker.create_asr_engine", lambda: LocalAsr())

    with serve(fake.app()) as provider, serve(native.app) as gateway:
        monkeypatch.setenv("DIARIZATION_LOCAL_URL", gateway.url)
        monkeypatch.delenv("DIARIZATION_PROVIDER", raising=False)
        yield World(factory, fake, provider, native, senko_runs, store)


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


async def transcribe(factory: Factory, message: dict[str, Any]) -> dict[str, Any]:
    """The local transcription step; returns the diarization message it publishes."""
    queue = AsyncMock()
    await _process_transcription(message, factory, queue)
    topic, diarization_message = queue.publish.await_args.args
    assert topic == "diarize"
    return dict(diarization_message)


async def diarization_of(factory: Factory, meeting_id: str) -> Diarization:
    async with factory() as session:
        return (await session.scalars(select(Diarization).where(Diarization.meeting_id == meeting_id))).one()


async def count(factory: Factory, model: type) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_local_transcript_and_external_speakers_become_word_attribution_and_turns(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    """The unit's done criterion; Properties 1-2 hold (a consented external route works)."""
    caplog.set_level(logging.INFO)
    message = await seed(world.factory)
    await world.link_provider()
    diarization_message = await transcribe(world.factory, message)

    await _process_diarization(dict(diarization_message), world.factory)

    attempt = await diarization_of(world.factory, message["meeting_id"])
    assert attempt.diarization_state == "completed" and attempt.processing_revision == 1
    assert (attempt.engine_name, attempt.engine_model) == ("deepgram", "nova-3")
    assert attempt.engine_external is True and attempt.engine_fallback_reason is None
    assert attempt.provider == "diar-engine-external" and attempt.speaker_count == 2
    assert world.senko_runs == [] and world.provider.requests == 1
    assert world.provider.authorizations == [f"Token {PROVIDER_KEY}"]
    async with world.factory() as session:
        speakers = list(await session.scalars(select(Speaker).order_by(Speaker.sequence)))
        assert [(s.raw_label, s.label) for s in speakers] == [("0", "Speaker 1"), ("1", "Speaker 2")]
        words = list(await session.scalars(select(TranscriptWord).order_by(TranscriptWord.sequence)))
        assert [(w.text, w.start_ms, w.end_ms) for w in words] == WORDS  # the local transcript is untouched
        assigned = list(
            await session.scalars(select(WordSpeakerAssignment).join(TranscriptWord).order_by(TranscriptWord.sequence))
        )
        assert [a.state for a in assigned] == ["assigned", "assigned", "assigned"]
        assert [a.speaker_id for a in assigned] == [speakers[0].id, speakers[1].id, speakers[1].id]
        # Turns: the one transcript turn is assigned to the speaker that covers most of it.
        turns = list(await session.scalars(select(SpeechTurn)))
        turn_assignments = list(await session.scalars(select(SpeakerAssignment)))
        assert len(turns) == 1 and [(a.turn_id, a.speaker_id) for a in turn_assignments] == [
            (turns[0].id, speakers[1].id)]
    assert "label_policy=provider" in caplog.text and "Hola" not in caplog.text and PROVIDER_KEY not in caplog.text


async def test_property_1_without_configuration_senko_answers_and_nothing_goes_out(world: World) -> None:
    message = await seed(world.factory)
    diarization_message = await transcribe(world.factory, message)
    await _process_diarization(diarization_message, world.factory)
    attempt = await diarization_of(world.factory, message["meeting_id"])
    assert (attempt.engine_name, attempt.engine_model) == ("senko", "senko-coreml")
    assert attempt.engine_external is False and attempt.engine_fallback_reason is None
    assert attempt.provider == "diar-engine-local" and attempt.diarization_state == "completed"
    assert len(world.senko_runs) == 1 and world.provider.requests == 0


@pytest.mark.parametrize("status", [503, 429])
async def test_transient_failure_with_fallback_runs_senko_once_and_records_the_real_provenance(
    world: World, status: int
) -> None:
    world.provider.status = status
    message = await seed(world.factory)
    await world.link_provider(fallback=True)
    diarization_message = await transcribe(world.factory, message)

    await _process_diarization(diarization_message, world.factory)

    attempt = await diarization_of(world.factory, message["meeting_id"])
    assert attempt.diarization_state == "completed"
    assert (attempt.engine_name, attempt.engine_model) == ("senko", "senko-coreml")
    assert attempt.engine_external is False and attempt.provider == "diar-engine-local"
    assert attempt.engine_fallback_reason in {"provider_unavailable", "provider_rate_limited"}
    assert len(world.senko_runs) == 1 and world.provider.requests == 1
    async with world.factory() as session:
        speakers = list(await session.scalars(select(Speaker).order_by(Speaker.sequence)))
        assert [s.raw_label for s in speakers] == ["SPEAKER_00", "SPEAKER_01"]


async def test_transient_failure_without_fallback_fails_the_revision_and_leaves_no_speakers(world: World) -> None:
    world.provider.status = 503
    message = await seed(world.factory)
    await world.link_provider(fallback=False)
    diarization_message = await transcribe(world.factory, message)

    with pytest.raises(ProviderError) as failure:
        await _process_diarization(diarization_message, world.factory)

    assert failure.value.code == "provider_unavailable"
    attempt = await diarization_of(world.factory, message["meeting_id"])
    assert (attempt.diarization_state, attempt.failure_cause) == ("failed", "engine_failure")
    assert attempt.engine_name is None and world.senko_runs == []
    assert await count(world.factory, Speaker) == 0 and await count(world.factory, WordSpeakerAssignment) == 0


async def test_property_14_user_action_failures_never_change_the_engine(world: World) -> None:
    world.provider.status = 401
    message = await seed(world.factory)
    await world.link_provider(fallback=True)
    diarization_message = await transcribe(world.factory, message)
    with pytest.raises(ProviderError) as failure:
        await _process_diarization(diarization_message, world.factory)
    assert failure.value.code == "provider_auth"
    assert world.senko_runs == [] and world.provider.requests == 1
    assert (await diarization_of(world.factory, message["meeting_id"])).diarization_state == "failed"


async def test_property_2_without_consent_nothing_is_sent_and_senko_is_not_used(world: World) -> None:
    message = await seed(world.factory)
    await world.link_provider(consented=False)
    diarization_message = await transcribe(world.factory, message)
    with pytest.raises(ProviderError) as failure:
        await _process_diarization(diarization_message, world.factory)
    assert failure.value.code == "consent_missing"
    assert world.provider.requests == 0 and world.senko_runs == []
    assert (await diarization_of(world.factory, message["meeting_id"])).diarization_state == "failed"


async def test_a_pair_the_matrix_does_not_offer_is_never_sent(world: World) -> None:
    """AssemblyAI speaker labels are not verified for Spanish yet, so the matrix does not offer them."""
    message = await seed(world.factory)
    await world.link_provider(kind="assemblyai", model="universal-2")
    diarization_message = await transcribe(world.factory, message)
    with pytest.raises(ProviderError) as failure:
        await _process_diarization(diarization_message, world.factory)
    assert failure.value.code == "provider_unsupported"
    assert world.provider.requests == 0 and world.senko_runs == []


async def test_property_15_redelivery_does_not_duplicate_speakers_or_call_any_engine(world: World) -> None:
    message = await seed(world.factory)
    diarization_message = await transcribe(world.factory, message)
    await _process_diarization(dict(diarization_message), world.factory)  # local
    first = (len(world.senko_runs), await count(world.factory, Speaker), await count(world.factory, SpeakerAssignment),
             await count(world.factory, WordSpeakerAssignment))
    await world.link_provider()  # the owner switches to the provider
    await _process_diarization(dict(diarization_message), world.factory)  # the same delivery arrives again
    assert (len(world.senko_runs), await count(world.factory, Speaker), await count(world.factory, SpeakerAssignment),
            await count(world.factory, WordSpeakerAssignment)) == first
    assert await count(world.factory, Diarization) == 1 and world.provider.requests == 0
    attempt = await diarization_of(world.factory, message["meeting_id"])
    assert attempt.engine_name == "senko" and attempt.engine_external is False  # the first provenance stays


async def test_retry_after_a_provider_failure_completes_one_revision_without_duplicates(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.provider.status = 503
    message = await seed(world.factory)
    await world.link_provider(fallback=False)
    diarization_message = await transcribe(world.factory, message)
    with pytest.raises(ProviderError):
        await _process_diarization(dict(diarization_message), world.factory)
    await _process_diarization(dict(diarization_message), world.factory)  # redelivery alone does not retry
    assert world.provider.requests == 1

    world.provider.status = 200
    store = SimpleNamespace(inspect=AsyncMock(return_value="available"))
    monkeypatch.setattr("app.diarization.worker.create_object_store", lambda: store)
    repository = DiarizationRepository(world.factory)
    async with world.factory() as session, session.begin():  # the explicit retry of the same revision
        assert await repository.retry_failed_revision(session, message["meeting_id"], 1) is not None
    queue = AsyncMock()
    assert await repository.publish_pending_revision(message["meeting_id"], 1, queue)
    retry_message = dict(queue.publish.await_args.args[1])
    await _process_diarization(dict(retry_message), world.factory)
    await _process_diarization(dict(retry_message), world.factory)  # and a late redelivery adds nothing

    attempt = await diarization_of(world.factory, message["meeting_id"])
    assert attempt.diarization_state == "completed" and attempt.engine_name == "deepgram"
    assert world.provider.requests == 2 and world.senko_runs == []
    assert await count(world.factory, Diarization) == 1 and await count(world.factory, Speaker) == 2
    assert await count(world.factory, WordSpeakerAssignment) == 3


async def test_a_change_applies_to_the_next_attempt_without_restarting_anything(world: World) -> None:
    first = await seed(world.factory)
    await _process_diarization(await transcribe(world.factory, first), world.factory)
    assert (await diarization_of(world.factory, first["meeting_id"])).engine_external is False
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
    await _process_diarization(await transcribe(world.factory, second), world.factory)
    external = await diarization_of(world.factory, meeting)
    assert (external.engine_name, external.engine_external) == ("deepgram", True)
    assert await count(world.factory, Transcript) == 2
