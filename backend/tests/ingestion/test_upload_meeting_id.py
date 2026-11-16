"""The upload endpoint confirms the meeting id and titles new meetings by file name."""

from __future__ import annotations

import json
import uuid
from io import BytesIO
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.schemas import AuthenticatedUser
from app.infra.models import Meeting
from app.ingestion import router as ingestion_router
from tests.media_samples import WEBM

_FILE_NAME = "Quarterly sales review.webm"


class _SyntheticObjectStore:
    async def save_stream(self, key: str, _content: object, _content_type: str) -> str:
        return f"synthetic/{key}"

    async def delete(self, _reference: str) -> None:
        return None


def _user() -> AuthenticatedUser:
    return AuthenticatedUser(
        id="synthetic-owner",
        email="synthetic-owner@example.test",
        name="Synthetic owner",
        is_sales=True,
    )


@pytest.fixture
def patched_infrastructure(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    queue = SimpleNamespace(connect=AsyncMock(), publish=AsyncMock(), disconnect=AsyncMock())
    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(ingestion_router, "_get_object_store", Mock(return_value=_SyntheticObjectStore()))
    monkeypatch.setattr(ingestion_router, "_get_queue", Mock(return_value=queue))
    monkeypatch.setattr(ingestion_router, "create_engine", Mock(return_value=engine))
    monkeypatch.setattr(
        ingestion_router, "create_session_factory", Mock(return_value=session_factory)
    )


async def _upload(meeting_id: str, idempotency_key: str) -> dict[str, Any]:
    return await ingestion_router.upload_recording(
        audio=UploadFile(filename=_FILE_NAME, file=BytesIO(WEBM + b"synthetic-audio")),
        video=None,
        data=json.dumps(
            {
                "meeting_id": meeting_id,
                "idempotency_key": idempotency_key,
                "capture_origin": "web_upload",
                "duration_seconds": 3,
                "video_presence": "absent",
            }
        ),
        user=_user(),
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("patched_infrastructure")
async def test_new_upload_and_idempotent_retry_return_the_sent_meeting_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id = str(uuid.uuid4())
    idempotency_key = str(uuid.uuid4())

    first = await _upload(meeting_id, idempotency_key)
    retry = await _upload(meeting_id, idempotency_key)

    assert first["meeting_id"] == meeting_id
    assert retry["meeting_id"] == meeting_id
    assert retry["recording_id"] == first["recording_id"]
    assert first["state"] == "transcribing"

    async with session_factory() as session:
        meeting = await session.get(Meeting, meeting_id)
    assert meeting is not None
    assert meeting.title == _FILE_NAME
