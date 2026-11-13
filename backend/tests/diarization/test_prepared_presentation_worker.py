"""Database/worker integration; only external inference/store/queue are injected."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.schemas import AuthenticatedUser
from app.diarization.diarization_engine import DiarizationCapabilities, DiarizationResult, SpeakerSegment
from app.diarization.repository import DiarizationRepository
from app.diarization.worker import _process_diarization
from app.infra.models import Diarization, Speaker, SpeakerReview, SpeechTurn, Transcript
from app.meetings.router import get_diarization
from app.transcription.asr_engine import ASRCapabilities, TranscriptionResult, TranscriptionSegment, WordInterval
from app.transcription.worker import _process_transcription
from tests.diarization.test_worker import _create_meeting, _create_recording


@pytest.mark.asyncio
@pytest.mark.parametrize("ambiguous", [False, True])
async def test_parent_commit_final_handoff_activation_and_redelivery(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch, ambiguous: bool
) -> None:
    monkeypatch.setenv("ASR_GRANULAR_PRESENTATION", "1")
    meeting = _create_meeting("projection-meeting", "recording")
    recording = _create_recording(meeting.id, "recordings/synthetic.wav", 1)
    async with session_factory() as session, session.begin():
        session.add_all([meeting, recording])
    segment = TranscriptionSegment("One two.", 0, 900, [WordInterval("One", 0, 200), WordInterval(" two.", 600, 900)])
    asr = Mock()
    asr.capabilities.return_value = ASRCapabilities(True, True)
    asr.transcribe = AsyncMock(return_value=TranscriptionResult([segment]))
    diar = Mock()
    diar.capabilities.return_value = DiarizationCapabilities(True, "diar-engine-local")
    regions = [SpeakerSegment("a", 0, 900), SpeakerSegment("b", 600, 900)] if ambiguous else [
        SpeakerSegment("a", 0, 200), SpeakerSegment("b", 600, 900), SpeakerSegment("empty", 950, 1000)]
    diar.diarize = AsyncMock(return_value=DiarizationResult(regions, len(regions)))
    queue = AsyncMock()
    with patch("app.transcription.worker.create_asr_engine", return_value=asr), patch(
        "app.transcription.worker.create_diarization_engine", return_value=diar
    ):
        await _process_transcription({"meeting_id": meeting.id, "owner_id": meeting.created_by,
                                      "recording_id": recording.id, "audio_ref": "untrusted"}, session_factory, queue)
    asr.transcribe.assert_awaited_once()
    assert asr.transcribe.call_args.args[0] == recording.audio_ref
    assert diar.diarize.call_args.args[0] == recording.audio_ref
    async with session_factory() as session:
        parent = (await session.scalars(select(SpeechTurn))).one()
        transcript = (await session.scalars(select(Transcript))).one()
        pending = (await session.scalars(select(Diarization))).one()
        assert (parent.text, parent.start_ms, parent.end_ms) == ("One two.", 0, 900)
        assert pending.diarization_state == "pending" and pending.presentation is None
        assert pending.prepared_result is not None
        payload = json.dumps(pending.prepared_result)
        for forbidden in ["One", "two.", "alignment", "words", "no_speech_prob", "recordings/", "untrusted"]:
            assert forbidden not in payload
        assert not (await session.scalars(select(SpeakerReview))).all()
    message = queue.publish.call_args.args[1]
    assert set(message) == {"meeting_id", "owner_id", "recording_id", "processing_revision"}
    store = Mock(inspect=AsyncMock(return_value="available"))
    with patch("app.diarization.worker.create_object_store", return_value=store), patch(
        "app.diarization.worker.create_diarization_engine", side_effect=AssertionError("must not repeat inference")
    ):
        original_complete = DiarizationRepository.complete_revision

        async def fail_after_flush(self: DiarizationRepository, *args: Any, **kwargs: Any) -> Any:
            await original_complete(self, *args, **kwargs)
            raise RuntimeError("synthetic failure after final flush")

        with patch.object(DiarizationRepository, "complete_revision", fail_after_flush), pytest.raises(RuntimeError):
            await _process_diarization(message, session_factory)
        async with session_factory() as session:
            failed = await session.get(Diarization, pending.id)
            assert failed is not None and failed.diarization_state == "failed"
            assert failed.presentation is None and failed.prepared_result is not None
            assert not (await session.scalars(select(SpeakerReview))).all()
            assert not (await session.scalars(select(Speaker))).all()
        async with session_factory() as session, session.begin():
            await DiarizationRepository(session_factory).retry_failed_revision(session, meeting.id, 1)
        await _process_diarization(message, session_factory)
        await _process_diarization(message, session_factory)
    async with session_factory() as session:
        completed = await session.get(Diarization, pending.id)
        assert completed is not None
        assert completed.prepared_result is None
        assert completed.presentation is not None
        assert completed.presentation["transcript_id"] == transcript.id
        assert completed.presentation["diarization_id"] == pending.id
        assert completed.diarization_state == "completed"
        assert len((await session.scalars(select(SpeakerReview))).all()) == 1
        pieces = completed.presentation["pieces"]
        assert isinstance(pieces, list)
        if ambiguous:
            assert len(pieces) == 1 and pieces[0]["speaker_id"] is None
            assert pieces[0]["char_start"] == 0 and pieces[0]["char_end"] == len(parent.text)
        else:
            assert len(pieces) == 2
            assert len((await session.scalars(select(Speaker))).all()) == 3
        persisted_parent = await session.get(SpeechTurn, parent.id)
        assert persisted_parent is not None
        assert persisted_parent.text == parent.text

    # The extension is opt-in and uses exactly the existing owner/sales boundary.
    owner = AuthenticatedUser(id=meeting.created_by, email="synthetic@example.test", name="Synthetic", is_sales=True)
    disposable_engine = Mock(dispose=AsyncMock())
    with patch("app.meetings.router.create_engine", return_value=disposable_engine), patch(
        "app.meetings.router.create_session_factory", return_value=session_factory
    ):
        v1 = await get_diarization(meeting.id, owner)
        assert "presentation" not in v1 and "prepared_result" not in v1
        v2 = await get_diarization(meeting.id, owner, presentation_version=2)
        assert v2["presentation"] == completed.presentation
        assert "prepared_result" not in json.dumps(v2) and "raw_label" not in json.dumps(v2)
        stranger = owner.model_copy(update={"id": "another-owner"})
        with pytest.raises(HTTPException) as denied:
            await get_diarization(meeting.id, stranger, presentation_version=2)
        assert denied.value.status_code == 404
        with pytest.raises(HTTPException) as denied:
            await get_diarization(meeting.id, owner.model_copy(update={"is_sales": False}), presentation_version=2)
        assert denied.value.status_code == 403
        async with session_factory() as session, session.begin():
            expired_source = await session.get(Transcript, transcript.id)
            assert expired_source is not None
            expired_source.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        expired_response = await get_diarization(meeting.id, owner, presentation_version=2)
        assert expired_response["presentation"] is None


@pytest.mark.asyncio
async def test_auxiliary_failure_does_not_hide_or_fragment_valid_asr(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASR_GRANULAR_PRESENTATION", "1")
    meeting = _create_meeting("fallback-meeting", "recording")
    recording = _create_recording(meeting.id, "recordings/synthetic.wav", 1)
    async with session_factory() as session, session.begin():
        session.add_all([meeting, recording])
    asr = Mock(capabilities=Mock(return_value=ASRCapabilities(True, True)), transcribe=AsyncMock(
        return_value=TranscriptionResult([TranscriptionSegment("One two.", 0, 900, [
            WordInterval("One", 0, 200), WordInterval(" two.", 600, 900)
        ])])))
    diar = Mock(capabilities=Mock(return_value=DiarizationCapabilities(True, "local")),
                diarize=AsyncMock(side_effect=RuntimeError("synthetic inference failure")))
    queue = AsyncMock()
    with patch("app.transcription.worker.create_asr_engine", return_value=asr), patch(
        "app.transcription.worker.create_diarization_engine", return_value=diar
    ):
        await _process_transcription({"meeting_id": meeting.id, "owner_id": meeting.created_by,
                                      "recording_id": recording.id, "audio_ref": recording.audio_ref},
                                     session_factory, queue)
    async with session_factory() as session:
        sources = (await session.scalars(select(SpeechTurn))).all()
        assert [(s.text, s.start_ms, s.end_ms) for s in sources] == [("One two.", 0, 900)]
        assert not (await session.scalars(select(Diarization))).all()
    assert queue.publish.await_count == 1
    assert "words" not in json.dumps(queue.publish.call_args.args[1])
