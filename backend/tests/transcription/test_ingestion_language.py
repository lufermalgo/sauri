"""RED contract tests for explicit playback-source capture metadata."""

from __future__ import annotations

import json
import uuid
from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import UploadFile

from app.ingestion import router
from tests.media_samples import WEBM


def _payload(**overrides: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "meeting_id": "meeting-synthetic-1",
        "idempotency_key": "capture-synthetic-1",
        "capture_origin": "chrome_extension",
        "duration_seconds": 12,
        "video_presence": "muxed",
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("language", [None, "es", "auto", "en"])
async def test_ingestion_forwards_optional_language(
    monkeypatch: pytest.MonkeyPatch, language,
) -> None:
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from app.auth.schemas import AuthenticatedUser
    from app.infra.models import Meeting

    meeting_id = "meeting-owned-synthetic"
    owner_id = "owner-synthetic"
    recording_id = "recording-synthetic"
    meeting = Meeting(
        id=meeting_id,
        meet_link=None,
        title=None,
        origin="manual",
        process_state="recording",
        created_by=owner_id,
        created_at=datetime.now(UTC),
    )

    class _SessionContext:
        async def __aenter__(self) -> _SessionContext:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        def begin(self) -> _SessionContext:
            return self

    session = _SessionContext()
    session.get = AsyncMock(return_value=meeting)  # type: ignore[attr-defined]
    engine = Mock()
    engine.dispose = AsyncMock()
    store = Mock()
    store.save_stream = AsyncMock(return_value="synthetic/audio-object")
    queue = Mock()
    queue.connect = AsyncMock()
    queue.publish = AsyncMock()
    queue.disconnect = AsyncMock()
    monkeypatch.setattr(router, "_get_object_store", Mock(return_value=store))
    monkeypatch.setattr(router, "_get_queue", Mock(return_value=queue))
    monkeypatch.setattr(router, "create_engine", Mock(return_value=engine))
    monkeypatch.setattr(
        router, "create_session_factory", Mock(return_value=Mock(return_value=session))
    )
    monkeypatch.setattr(router, "preflight_ingestion", AsyncMock(return_value=None))
    process_ingestion = AsyncMock(
        return_value=(SimpleNamespace(id=recording_id, process_state="recording"), True)
    )
    monkeypatch.setattr(router, "process_ingestion", process_ingestion)
    monkeypatch.setattr(
        router, "record_transition", AsyncMock(return_value=SimpleNamespace(successful=True))
    )
    monkeypatch.setattr(router, "create_processing_generation", AsyncMock(return_value=1))

    result = await router.upload_recording(
        audio=UploadFile(filename="synthetic.webm", file=BytesIO(WEBM + b"synthetic audio")),
        video=None,
        data=json.dumps(_payload(meeting_id=meeting_id, video_presence="absent", language=language)),
        user=AuthenticatedUser(
            id=owner_id,
            email="owner@example.test",
            name="Synthetic Owner",
            is_sales=True,
        ),
    )

    assert result["recording_id"] == recording_id
    queue.publish.assert_awaited_once()
    topic = queue.publish.await_args.kwargs["topic"]
    message = queue.publish.await_args.kwargs["message"]
    assert topic == "transcribe"
    assert message == {
        "meeting_id": meeting_id,
        "owner_id": owner_id,
        "recording_id": recording_id,
        "audio_ref": "synthetic/audio-object",
        "generation": 1,
        "job_id": message["job_id"],
        **({"language": language} if language else {}),
    }
    assert uuid.UUID(message["job_id"])


@pytest.mark.parametrize("language", ["es-CO", "spa", "ES", "a", "", " auto", "en\n", 1])
def test_ingestion_rejects_non_two_letter_language(language):
    from pydantic import ValidationError

    from app.ingestion.schemas import IngestionData

    with pytest.raises(ValidationError):
        IngestionData(**_payload(language=language))
