"""Integration tests for the speaker-identification (diarization) module.

# Feature: speaker-identification
Tasks: 15.1, 15.2, 15.4
Validates: Requirements 1.1, 1.2, 1.7, 1.8, 4.1, 4.3, 10.2

NOTE: The mocks/simulated transports here act ONLY within tests to isolate
I/O boundaries (queue, engine, network). Production code is 100% real.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.diarization.worker import start_worker
from app.infra.models import Meeting, SessionRecording
from app.infra.queue_rabbitmq import _message_signature


def _create_recording_for_meeting(meeting_id: str) -> SessionRecording:
    return SessionRecording(
        id=str(uuid.uuid4()),
        meeting_id=meeting_id,
        idempotency_key=str(uuid.uuid4()),
        capture_origin="chrome_extension",
        audio_ref="synthetic/recording.wav",
        video_ref=None,
        duration_seconds=12,
        interrupted=False,
        expires_at=None,
        finished_at=datetime.now(UTC),
    )

# ---------------------------------------------------------------------------
# Task 15.1 — Subscription to the "diarize" topic (Req 1.1)
# ---------------------------------------------------------------------------


class TestDiarizationWorkerSubscription:
    """The diarization worker subscribes to the 'diarize' topic on startup."""

    @pytest.mark.asyncio
    async def test_worker_subscribes_to_diarize_topic(self) -> None:
        """On startup, the worker subscribes to the 'diarize' topic (Req 1.1)."""
        mock_queue = AsyncMock()
        mock_queue.subscribe = AsyncMock()
        mock_session_factory = AsyncMock()

        await start_worker(mock_queue, mock_session_factory)

        mock_queue.subscribe.assert_called_once()
        call_args = mock_queue.subscribe.call_args
        assert call_args[0][0] == "diarize"
        assert callable(call_args[0][1])


# ---------------------------------------------------------------------------
# Task 15.1 — Publishing the Diarization_Message on transcript completion (Req 1.2)
# ---------------------------------------------------------------------------


class TestDiarizationMessagePublication:
    """Once a Transcript becomes available, a Diarization_Message is published."""

    @pytest.mark.asyncio
    async def test_publishes_diarize_on_transcript_completion(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """After persisting the Transcript, {meeting_id} is published to the 'diarize' topic (Req 1.2)."""
        from app.transcription.asr_engine import (
            ASRCapabilities,
            TranscriptionResult,
            TranscriptionSegment,
        )
        from app.transcription.worker import _process_transcription

        meeting_id = str(uuid.uuid4())
        async with session_factory() as session, session.begin():
            session.add(
                Meeting(
                    id=meeting_id,
                    meet_link="https://meet.google.com/abc-defg-hij",
                    origin="link",
                    calendar_invite_id=None,
                    scheduled_start_time=None,
                    process_state="recording",
                    failure_cause=None,
                    created_by="test-user",
                    created_at=datetime.now(UTC),
                )
            )
        recording = _create_recording_for_meeting(meeting_id)
        async with session_factory() as session, session.begin():
            session.add(recording)

        segments = [TranscriptionSegment(text="hola", start_ms=0, end_ms=1000)]
        result = TranscriptionResult(segments=segments, language="es-CO", supports_turns=True)
        engine = AsyncMock()
        engine.transcribe.return_value = result
        engine.capabilities = MagicMock(return_value=ASRCapabilities(supports_turns=True, is_local=True))

        mock_queue = AsyncMock()
        mock_queue.publish = AsyncMock()

        message = {
            "meeting_id": meeting_id,
            "owner_id": "test-user",
            "recording_id": recording.id,
            "audio_ref": "audio/test.webm",
        }
        with patch("app.transcription.worker.create_asr_engine", return_value=engine):
            await _process_transcription(message, session_factory, mock_queue)

        # The Diarization_Message must have been published with the meeting_id
        diarize_publications = [
            c for c in mock_queue.publish.call_args_list if c[0][0] == "diarize"
        ]
        assert len(diarize_publications) == 1
        assert diarize_publications[0][0][1] == {
            "meeting_id": meeting_id,
            "owner_id": "test-user",
            "recording_id": recording.id,
        }

    @pytest.mark.asyncio
    async def test_does_not_publish_if_there_is_no_transcript(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """If transcription fails (no segments), nothing is published to 'diarize'."""
        from app.transcription.asr_engine import (
            ASRCapabilities,
            TranscriptionResult,
        )
        from app.transcription.worker import _process_transcription

        meeting_id = str(uuid.uuid4())
        async with session_factory() as session, session.begin():
            session.add(
                Meeting(
                    id=meeting_id,
                    meet_link="https://meet.google.com/abc-defg-hij",
                    origin="link",
                    calendar_invite_id=None,
                    scheduled_start_time=None,
                    process_state="recording",
                    failure_cause=None,
                    created_by="test-user",
                    created_at=datetime.now(UTC),
                )
            )
        recording = _create_recording_for_meeting(meeting_id)
        async with session_factory() as session, session.begin():
            session.add(recording)

        result = TranscriptionResult(segments=[], language="es-CO", supports_turns=True)
        engine = AsyncMock()
        engine.transcribe.return_value = result
        engine.capabilities = MagicMock(return_value=ASRCapabilities(supports_turns=True, is_local=True))

        mock_queue = AsyncMock()
        mock_queue.publish = AsyncMock()

        message = {
            "meeting_id": meeting_id,
            "owner_id": "test-user",
            "recording_id": recording.id,
            "audio_ref": "audio/test.webm",
        }
        with patch("app.transcription.worker.create_asr_engine", return_value=engine):
            await _process_transcription(message, session_factory, mock_queue)

        diarize_publications = [
            c for c in mock_queue.publish.call_args_list if c[0][0] == "diarize"
        ]
        assert len(diarize_publications) == 0


# ---------------------------------------------------------------------------
# Task 15.2 — ack/nack and retries bounded by DIARIZATION_MAX_RETRIES
# Validates: Requirements 1.7, 1.8, 10.2
# ---------------------------------------------------------------------------


class TestDiarizeAckNackRetries:
    """Integration with RabbitMQJobQueue: ack on success, nack on failure, retries."""

    @pytest.mark.asyncio
    @patch.dict(
        os.environ,
        {"QUEUE_MESSAGE_SIGNING_KEY": "qa-synthetic-signing-key-32bytes-minimum"},
        clear=False,
    )
    async def test_ack_after_success(self) -> None:
        """Successful handler -> ack (Req 1.7)."""
        import json

        from app.infra.queue_rabbitmq import RabbitMQJobQueue

        queue = RabbitMQJobQueue("amqp://guest:guest@localhost/")
        queue._dlx_exchange = None

        async def ok_handler(_msg: Any) -> None:
            return None

        mock_message = AsyncMock()
        mock_message.body = json.dumps({"meeting_id": "abc"}).encode()
        mock_message.headers = {
            "x-sauri-signature": _message_signature("diarize", mock_message.body)
        }
        mock_message.ack = AsyncMock()
        mock_message.nack = AsyncMock()

        queue._channel = AsyncMock()
        queue._channel.is_closed = False
        mock_queue_obj = AsyncMock()
        queue._channel.declare_queue.return_value = mock_queue_obj

        captured: dict[str, Any] = {}

        async def capture_consume(cb: Any) -> None:
            captured["cb"] = cb

        mock_queue_obj.consume = capture_consume

        await queue.subscribe("diarize", ok_handler)
        await captured["cb"](mock_message)

        mock_message.ack.assert_awaited_once()
        mock_message.nack.assert_not_called()

    @pytest.mark.asyncio
    async def test_nack_after_exception_with_diarization_retries(self) -> None:
        """Handler raising an exception -> republishes with the counter +1 and acks while retries remain
        (Req 1.8, 10.2).

        Doesn't use nack(requeue=True): with no DLX configured that requeues
        the same message with no trace of retries, causing an infinite loop
        (a real bug that was observed). Instead a copy is republished with
        x-sauri-retries incremented and the original message is acked.
        """
        import json

        from app.infra.queue_rabbitmq import RabbitMQJobQueue

        with patch.dict(
            os.environ,
            {
                "DIARIZATION_MAX_RETRIES": "3",
                "QUEUE_MESSAGE_SIGNING_KEY": "qa-synthetic-signing-key-32bytes-minimum",
            },
            clear=False,
        ):
            queue = RabbitMQJobQueue("amqp://guest:guest@localhost/")
            queue._dlx_exchange = None

            async def failing_handler(_msg: Any) -> None:
                raise RuntimeError("engine failure")

            mock_message = AsyncMock()
            mock_message.body = json.dumps({"meeting_id": "abc"}).encode()
            mock_message.headers = {
                "x-sauri-signature": _message_signature("diarize", mock_message.body)
            }  # 0 previous retries
            mock_message.content_type = "application/json"
            mock_message.ack = AsyncMock()
            mock_message.nack = AsyncMock()

            queue._channel = AsyncMock()
            queue._channel.is_closed = False
            mock_queue_obj = AsyncMock()
            queue._channel.declare_queue.return_value = mock_queue_obj
            from pamqp.commands import Basic

            queue._channel.default_exchange.publish = AsyncMock(return_value=Basic.Ack())

            captured: dict[str, Any] = {}

            async def capture_consume(cb: Any) -> None:
                captured["cb"] = cb

            mock_queue_obj.consume = capture_consume

            await queue.subscribe("diarize", failing_handler)
            await captured["cb"](mock_message)

            # 0 < 3 retries -> republishes with x-sauri-retries=1 and acks the original
            mock_message.nack.assert_not_called()
            mock_message.ack.assert_awaited_once()
            queue._channel.default_exchange.publish.assert_awaited_once()
            published_message, kwargs = queue._channel.default_exchange.publish.call_args
            assert kwargs["routing_key"] == "diarize"
            assert published_message[0].headers["x-sauri-retries"] == 1


# ---------------------------------------------------------------------------
# Task 15.4 — HTTPS egress + Bearer auth from CloudProvider
# Validates: Requirements 4.1, 4.3
# ---------------------------------------------------------------------------


class TestCloudProviderHTTPSEgress:
    """CloudProvider transmits over HTTPS with an Authorization: Bearer header."""

    @pytest.mark.asyncio
    async def test_transmits_https_with_bearer(self) -> None:
        """The request goes out over HTTPS with 'Authorization: Bearer {api_key}' (Req 4.1, 4.3)."""
        from app.diarization.diarization_engine import DiarizationOptions

        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["scheme"] = request.url.scheme
            captured["auth"] = request.headers.get("Authorization")
            return httpx.Response(
                200,
                json={
                    "segments": [{"speaker": "S0", "start_ms": 0, "end_ms": 1000}],
                    "num_speakers": 1,
                },
            )

        transport = httpx.MockTransport(handler)

        env = {
            "DIARIZATION_CLOUD_ENDPOINT": "https://api.diarization.example.com/diarize",
            "DIARIZATION_CLOUD_API_KEY": "sk-secreta-123",
        }
        with patch.dict(os.environ, env, clear=False):
            from app.diarization.cloud_provider import CloudProvider

            provider = CloudProvider()

            # Inject the simulated transport ONLY in the test
            original_client = httpx.AsyncClient

            def client_factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
                kwargs["transport"] = transport
                return original_client(*args, **kwargs)

            with patch("app.diarization.cloud_provider.httpx.AsyncClient", client_factory):
                await provider.diarize("audio/test.wav", DiarizationOptions(duration_ms=10000))

        assert captured["scheme"] == "https"
        assert captured["url"].startswith("https://")
        assert captured["auth"] == "Bearer sk-secreta-123"
