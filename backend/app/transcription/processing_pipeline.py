"""Exact-revision, lease-fenced transcription/diarization and review finalization.

The upload path admits a revision in its own transaction. Only the dispatcher
publishes its committed outbox event; providers never run under a database lock.
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import (
    Diarization,
    Meeting,
    ProcessingRevision,
    ProcessingRevisionOutbox,
    ProcessingStage,
    RecordingProcessingState,
    SessionRecording,
    Speaker,
    SpeakerAssignment,
    SpeakerReview,
    SpeakerReviewItem,
    SpeechTurn,
    Transcript,
)
from app.meetings.processing_revision_service import lock_processing_state

Stage = str
_VALID_STAGES = frozenset({"transcription", "diarization"})
_LEASE = timedelta(minutes=20)


@dataclass(frozen=True)
class StageClaim:
    acquired: bool
    token: str | None = None
    output: dict[str, Any] | None = None


class ProcessingPipeline:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        transcription_provider: Callable[..., Awaitable[dict[str, Any]]],
        diarization_provider: Callable[..., Awaitable[dict[str, Any]]],
        excerpt_validator: Callable[..., Awaitable[dict[str, str]]],
        speaker_identity_matcher: Callable[..., Awaitable[Any]] | None = None,
    ) -> None:
        self._sessions = session_factory
        self._providers = {"transcription": transcription_provider, "diarization": diarization_provider}
        self._excerpts = excerpt_validator
        self._matcher = speaker_identity_matcher

    @staticmethod
    def _validate_stage(stage: Stage) -> None:
        if stage not in _VALID_STAGES:
            raise ValueError("unknown processing stage")

    async def claim_stage(
        self, revision_id: str, stage: Stage, *, lease_expires_at: datetime | None = None
    ) -> StageClaim:
        self._validate_stage(stage)
        async with self._sessions() as session, session.begin():
            # Lock the parent even for the first claim (before a stage row exists).
            revision = await session.scalar(
                select(ProcessingRevision).where(ProcessingRevision.id == revision_id).with_for_update()
            )
            if revision is None:
                raise ValueError("unknown processing revision")
            state = await session.get(RecordingProcessingState, revision.recording_id)
            if state is None or state.in_flight_revision_id != revision_id:
                return StageClaim(False)
            row = await session.scalar(
                select(ProcessingStage)
                .where(
                    ProcessingStage.processing_revision_id == revision_id,
                    ProcessingStage.stage == stage,
                )
                .with_for_update()
            )
            now = datetime.now(UTC)
            if row is not None:
                if row.status == "completed":
                    return StageClaim(False, output=row.output)
                if row.status == "running" and row.lease_expires_at is not None:
                    expiry = (
                        row.lease_expires_at.replace(tzinfo=UTC)
                        if row.lease_expires_at.tzinfo is None
                        else row.lease_expires_at
                    )
                    if expiry > now:
                        return StageClaim(False)
            token = str(uuid.uuid4())
            if row is None:
                row = ProcessingStage(
                    id=str(uuid.uuid4()), processing_revision_id=revision_id, stage=stage, status="running"
                )
                session.add(row)
            row.status = "running"
            row.lease_token = token
            row.lease_expires_at = lease_expires_at or now + _LEASE
            await session.flush()
            return StageClaim(True, token=token)

    async def process_stage(
        self,
        revision_id: str,
        stage: Stage,
        *,
        before_commit: Callable[[], Awaitable[Any]] | None = None,
    ) -> dict[str, Any] | None:
        claim = await self.claim_stage(revision_id, stage)
        if not claim.acquired:
            return claim.output
        async with self._sessions() as session:
            revision = await session.get(ProcessingRevision, revision_id)
            recording = await session.get(SessionRecording, revision.recording_id) if revision else None
            if recording is None:
                raise ValueError("recording not found")
            audio_ref = recording.audio_ref
        provider = self._providers[stage]
        # Callable providers accept the persisted reference; simple injected
        # test collaborators with no parameters remain supported.
        parameter_count = len(inspect.signature(provider).parameters)
        if parameter_count >= 2:
            result = await provider(audio_ref, recording)
        elif parameter_count == 1:
            result = await provider(audio_ref)
        else:
            result = await provider()
        if not isinstance(result, dict):
            raise ValueError("invalid stage output")
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(ProcessingStage)
                .where(
                    ProcessingStage.processing_revision_id == revision_id,
                    ProcessingStage.stage == stage,
                )
                .with_for_update()
            )
            if row is None or row.status != "running" or row.lease_token != claim.token:
                # A slower provider cannot overwrite a newer lease holder.
                return row.output if row is not None and row.status == "completed" else None
            revision = await session.get(ProcessingRevision, revision_id)
            recording = await session.get(SessionRecording, revision.recording_id) if revision else None
            state = await session.get(RecordingProcessingState, revision.recording_id) if revision else None
            if revision is None or recording is None or state is None or state.in_flight_revision_id != revision_id:
                return None
            if stage == "transcription":
                await self._persist_transcript(session, recording.meeting_id, revision_id, result)
            else:
                await self._persist_diarization(session, recording.meeting_id, revision, result)
            row.output = result
            row.status = "completed"
            row.lease_token = None
            row.lease_expires_at = None
            session.add(
                ProcessingRevisionOutbox(
                    id=str(uuid.uuid4()),
                    recording_id=recording.id,
                    processing_revision_id=revision_id,
                    event_type=f"{stage}_completed",
                    delivery_status="pending",
                    created_at=datetime.now(UTC),
                )
            )
            await session.flush()
            if before_commit is not None:
                await before_commit()
        return result

    @staticmethod
    async def _persist_transcript(
        session: AsyncSession, meeting_id: str, revision_id: str, result: dict[str, Any]
    ) -> None:
        segments = result.get("segments")
        if (
            not isinstance(segments, list)
            or not segments
            or not all(
                isinstance(segment.get("text"), str)
                and isinstance(segment.get("start_ms"), int)
                and isinstance(segment.get("end_ms"), int)
                and 0 <= segment["start_ms"] < segment["end_ms"]
                for segment in segments
            )
        ):
            raise ValueError("invalid transcript segments")
        transcript = Transcript(
            id=str(uuid.uuid4()),
            meeting_id=meeting_id,
            processing_revision_id=revision_id,
            language=result.get("language", "es-CO"),
            provider=result.get("provider", "processing_pipeline"),
            supports_turns=bool(result.get("supports_turns", True)),
            created_at=datetime.now(UTC),
        )
        session.add(transcript)
        for index, segment in enumerate(segments):
            session.add(
                SpeechTurn(
                    id=str(uuid.uuid4()),
                    transcript_id=transcript.id,
                    text=segment["text"],
                    start_ms=segment["start_ms"],
                    end_ms=segment["end_ms"],
                    sequence=index,
                )
            )
        await session.flush()

    @staticmethod
    async def _persist_diarization(
        session: AsyncSession, meeting_id: str, revision: ProcessingRevision, result: dict[str, Any]
    ) -> None:
        transcript = await session.scalar(
            select(Transcript).where(
                Transcript.meeting_id == meeting_id, Transcript.processing_revision_id == revision.id
            )
        )
        if transcript is None:
            raise ValueError("diarization requires the exact revision transcript")
        keys = result.get("speakers")
        if (
            not isinstance(keys, list)
            or not all(isinstance(key, str) and key for key in keys)
            or len(set(keys)) != len(keys)
        ):
            raise ValueError("invalid diarization speakers")
        segments = result.get("segments")
        if not isinstance(segments, list) or not all(
            isinstance(segment, dict)
            and segment.get("raw_label") in keys
            and isinstance(segment.get("start_ms"), int)
            and isinstance(segment.get("end_ms"), int)
            and 0 <= segment["start_ms"] < segment["end_ms"]
            for segment in segments
        ):
            raise ValueError("invalid diarization segments")
        if keys and not segments:
            raise ValueError("speaker intervals unavailable")
        now = datetime.now(UTC)
        diarization = Diarization(
            id=str(uuid.uuid4()),
            meeting_id=meeting_id,
            transcript_id=transcript.id,
            processing_revision_id=revision.id,
            processing_revision=revision.revision,
            provider=result.get("provider", "processing_pipeline"),
            speaker_count=len(keys),
            diarization_state="completed",
            created_at=now,
            updated_at=now,
        )
        session.add(diarization)
        speakers = []
        for index, key in enumerate(keys, 1):
            speaker = Speaker(
                id=str(uuid.uuid4()),
                diarization_id=diarization.id,
                raw_label=key,
                label=f"Speaker {index}",
                sequence=index,
            )
            session.add(speaker)
            speakers.append(speaker)
        turns = (await session.scalars(select(SpeechTurn).where(SpeechTurn.transcript_id == transcript.id))).all()
        from app.diarization.assignment import assign_turns
        from app.diarization.diarization_engine import SpeakerSegment
        from app.diarization.labeling import Speaker as LabeledSpeaker

        intervals = [SpeakerSegment(**segment) for segment in segments]
        labeled = [LabeledSpeaker(raw_label=s.raw_label, label=s.label, sequence=s.sequence) for s in speakers]
        speaker_by_label = {s.raw_label: s for s in speakers}
        for turn_id, assigned, overlap_ms in assign_turns(list(turns), intervals, labeled):
            speaker_id = speaker_by_label[assigned.raw_label].id
            session.add(
                SpeakerAssignment(
                    id=str(uuid.uuid4()),
                    diarization_id=diarization.id,
                    turn_id=turn_id,
                    speaker_id=speaker_id,
                    overlap_ms=overlap_ms,
                )
            )
        await session.flush()

    async def finalize(
        self, revision_id: str, *, before_commit: Callable[[], Awaitable[Any]] | None = None
    ) -> dict[str, Any] | None:
        async with self._sessions() as session, session.begin():
            revision = await session.get(ProcessingRevision, revision_id)
            if revision is None:
                raise ValueError("unknown processing revision")
            recording = await session.get(SessionRecording, revision.recording_id)
            if recording is None:
                raise ValueError("recording not found")
            state = await lock_processing_state(session, recording.meeting_id)
            if state is None:
                raise ValueError("processing state not found")
            if state.active_processing_revision_id == revision_id and state.in_flight_revision_id is None:
                return await self._review_dict(session, recording.id, revision)
            if (
                state.in_flight_revision_id != revision_id
                or state.active_processing_revision_id != revision.admitted_active_revision_id
            ):
                return None  # stale delivery cannot activate or clear another candidate
            stages = (
                await session.scalars(
                    select(ProcessingStage).where(
                        ProcessingStage.processing_revision_id == revision_id,
                        ProcessingStage.status == "completed",
                    )
                )
            ).all()
            if {row.stage for row in stages} != _VALID_STAGES:
                return None
            diarization = await session.scalar(
                select(Diarization).where(
                    Diarization.meeting_id == recording.meeting_id,
                    Diarization.processing_revision_id == revision_id,
                    Diarization.diarization_state == "completed",
                )
            )
            transcript = await session.scalar(
                select(Transcript).where(
                    Transcript.meeting_id == recording.meeting_id, Transcript.processing_revision_id == revision_id
                )
            )
            if diarization is None or transcript is None:
                return None
            speakers = (
                await session.scalars(
                    select(Speaker).where(Speaker.diarization_id == diarization.id).order_by(Speaker.sequence)
                )
            ).all()
            if inspect.signature(self._excerpts).parameters:
                excerpts = await self._excerpts(recording, revision, speakers)
            else:
                excerpts = await self._excerpts()
            if (
                not isinstance(excerpts, dict)
                or set(excerpts) != {speaker.raw_label for speaker in speakers}
                or not all(isinstance(value, str) and value for value in excerpts.values())
            ):
                raise ValueError("validated excerpts unavailable")
            review = SpeakerReview(
                id=str(uuid.uuid4()),
                meeting_id=recording.meeting_id,
                processing_revision=revision.revision,
                status="pending" if speakers else "complete",
                created_at=datetime.now(UTC),
            )
            session.add(review)
            for speaker in speakers:
                session.add(
                    SpeakerReviewItem(
                        id=str(uuid.uuid4()),
                        review_id=review.id,
                        speaker_key=speaker.raw_label,
                        current_label=speaker.label,
                        excerpt_ref=excerpts[speaker.raw_label],
                        attribution_state="uncertain",
                        version=1,
                    )
                )
            state.active_processing_revision_id = revision_id
            state.in_flight_revision_id = None
            meeting = await session.get(Meeting, recording.meeting_id)
            if meeting is not None and meeting.process_state == "transcribing":
                from app.meetings.service import record_transition

                await record_transition(session, meeting, "transcription_completed")
            await session.flush()
            if before_commit is not None:
                await before_commit()
            return await self._review_dict(session, recording.id, revision)

    async def get_review(self, recording_id: str) -> dict[str, Any] | None:
        async with self._sessions() as session, session.begin():
            recording = await session.get(SessionRecording, recording_id)
            if recording is None:
                return None
            state = await lock_processing_state(session, recording.meeting_id)
            if state is None:
                return None
            if state.active_processing_revision_id is None:
                # Legacy revision 1 was backfilled without inferring readiness.
                # A competing admission wins the same lock and fences lazy activation.
                if state.in_flight_revision_id is not None or state.legacy_compatibility_revision_id is None:
                    return None
                revision = await session.get(ProcessingRevision, state.legacy_compatibility_revision_id)
                if revision is None or revision.recording_id != recording_id:
                    return None
                transcript = await session.scalar(
                    select(Transcript).where(
                        Transcript.meeting_id == recording.meeting_id, Transcript.processing_revision_id == revision.id
                    )
                )
                diarization = await session.scalar(
                    select(Diarization).where(
                        Diarization.meeting_id == recording.meeting_id,
                        Diarization.processing_revision_id == revision.id,
                        Diarization.diarization_state == "completed",
                    )
                )
                if transcript is None or diarization is None or diarization.transcript_id != transcript.id:
                    return None
                speakers = (
                    await session.scalars(
                        select(Speaker).where(Speaker.diarization_id == diarization.id).order_by(Speaker.sequence)
                    )
                ).all()
                if len(speakers) != diarization.speaker_count:
                    return None
                # Do not activate incomplete legacy rows or synthesize excerpts.
                if inspect.signature(self._excerpts).parameters:
                    excerpts = await self._excerpts(recording, revision, speakers)
                else:
                    excerpts = await self._excerpts()
                if not isinstance(excerpts, dict) or set(excerpts) != {speaker.id for speaker in speakers}:
                    return None
                if not all(isinstance(value, str) and value for value in excerpts.values()):
                    return None
                review = SpeakerReview(
                    id=str(uuid.uuid4()),
                    meeting_id=recording.meeting_id,
                    processing_revision=revision.revision,
                    status="pending" if speakers else "complete",
                    created_at=datetime.now(UTC),
                )
                session.add(review)
                for speaker in speakers:
                    session.add(
                        SpeakerReviewItem(
                            id=str(uuid.uuid4()),
                            review_id=review.id,
                            speaker_key=speaker.id,
                            current_label=speaker.label,
                            excerpt_ref=excerpts[speaker.id],
                            attribution_state="uncertain",
                            version=1,
                        )
                    )
                state.active_processing_revision_id = revision.id
                await session.flush()
            revision = await session.get(ProcessingRevision, state.active_processing_revision_id)
            return await self._review_dict(session, recording_id, revision) if revision is not None else None

    @staticmethod
    async def _review_dict(
        session: AsyncSession, recording_id: str, revision: ProcessingRevision
    ) -> dict[str, Any] | None:
        review = await session.scalar(
            select(SpeakerReview)
            .join(SessionRecording, SessionRecording.meeting_id == SpeakerReview.meeting_id)
            .where(SessionRecording.id == recording_id, SpeakerReview.processing_revision == revision.revision)
        )
        if review is None:
            return None
        items = (
            await session.scalars(
                select(SpeakerReviewItem)
                .where(SpeakerReviewItem.review_id == review.id)
                .order_by(SpeakerReviewItem.speaker_key)
            )
        ).all()
        return {
            "review_id": review.id,
            "processing_revision_id": revision.id,
            "speaker_keys": [item.speaker_key for item in items],
            "excerpts": {item.speaker_key: item.excerpt_ref for item in items},
        }

    async def count_stage_outputs(self, revision_id: str) -> int:
        async with self._sessions() as session:
            return (
                await session.scalar(
                    select(func.count())
                    .select_from(ProcessingStage)
                    .where(ProcessingStage.processing_revision_id == revision_id, ProcessingStage.status == "completed")
                )
                or 0
            )

    async def is_stage_complete(self, revision_id: str, stage: str) -> bool:
        self._validate_stage(stage)
        async with self._sessions() as session:
            return bool(
                await session.scalar(
                    select(ProcessingStage.id).where(
                        ProcessingStage.processing_revision_id == revision_id,
                        ProcessingStage.stage == stage,
                        ProcessingStage.status == "completed",
                    )
                )
            )

    async def count_outbox_events(self, revision_id: str, stage: str) -> int:
        self._validate_stage(stage)
        async with self._sessions() as session:
            return (
                await session.scalar(
                    select(func.count())
                    .select_from(ProcessingRevisionOutbox)
                    .where(
                        ProcessingRevisionOutbox.processing_revision_id == revision_id,
                        ProcessingRevisionOutbox.event_type == f"{stage}_completed",
                    )
                )
                or 0
            )

    async def count_reviews(self, recording_id: str, revision_id: str) -> int:
        async with self._sessions() as session:
            revision = await session.get(ProcessingRevision, revision_id)
            if revision is None or revision.recording_id != recording_id:
                return 0
            return (
                await session.scalar(
                    select(func.count())
                    .select_from(SpeakerReview)
                    .join(SessionRecording, SessionRecording.meeting_id == SpeakerReview.meeting_id)
                    .where(SessionRecording.id == recording_id, SpeakerReview.processing_revision == revision.revision)
                )
                or 0
            )
