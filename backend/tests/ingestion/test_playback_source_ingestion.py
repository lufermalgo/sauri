"""RED contract tests for explicit playback-source capture metadata."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, UploadFile

from app.ingestion import router
from app.ingestion.schemas import IngestionData


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


@pytest.mark.parametrize(
    ("overrides", "expected_presence", "expected_offset"),
    [
        ({"video_presence": "muxed"}, "muxed", None),
        ({"video_presence": "absent"}, "absent", None),
        (
            {
                "video_presence": "separate",
                "video_offset_ms": -125,
            },
            "separate",
            -125,
        ),
        (
            {
                "video_presence": "separate",
                "video_offset_ms": 250,
            },
            "separate",
            250,
        ),
    ],
)
def test_ingestion_contract_preserves_explicit_capture_evidence(
    overrides: dict[str, object], expected_presence: str, expected_offset: int | None
) -> None:
    data = IngestionData(**_payload(**overrides))

    assert data.video_presence == expected_presence
    assert data.video_offset_ms == expected_offset


@pytest.mark.parametrize(
    "overrides",
    [
        {"video_presence": None},  # Presence evidence is required.
        {"video_presence": "separate"},  # Separate video requires an offset.
        {"video_presence": "muxed", "video_offset_ms": 12},
        {"video_presence": "absent", "video_offset_ms": -12},
        {
            "capture_mode": "separate",
            "video_presence": "separate",
            "video_offset_ms": 1.5,
        },
    ],
)
def test_inconsistent_or_incomplete_capture_metadata_is_rejected(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        IngestionData(**_payload(**overrides))


@pytest.mark.asyncio
async def test_invalid_capture_metadata_returns_422_before_object_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def storage_must_not_be_initialized() -> None:
        raise AssertionError("invalid metadata must be rejected before storage")

    monkeypatch.setattr(router, "_get_object_store", storage_must_not_be_initialized)
    audio = UploadFile(filename="synthetic.webm", file=None)  # type: ignore[arg-type]

    with pytest.raises(HTTPException) as error:
        await router.upload_recording(
            audio=audio,
            video=None,
            data=json.dumps(
                _payload(
                    video_presence="separate",
                    video_offset_ms=40,
                )
            ),
            user=type("User", (), {"id": "synthetic-user"})(),
        )

    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_invalid_json_returns_same_422_detail_and_chains_parse_error() -> None:
    audio = UploadFile(filename="synthetic.webm", file=BytesIO(b"audio"))

    with pytest.raises(HTTPException) as error:
        await router.upload_recording(
            audio=audio,
            video=None,
            data="not-json",
            user=type("User", (), {"id": "synthetic-user"})(),
        )

    assert type(error.value) is HTTPException
    assert error.value.status_code == 422
    assert error.value.detail == (
        "Invalid ingestion data: Expecting value: line 1 column 1 (char 0)"
    )
    assert isinstance(error.value.__cause__, json.JSONDecodeError)


@pytest.mark.parametrize(
    ("video_presence", "include_video", "video_offset_ms"),
    [
        ("muxed", True, None),  # Muxed is the single-object upload path.
        ("absent", True, None),  # An uploaded video contradicts absent evidence.
        ("separate", False, 40),  # Separate requires a distinct video object.
    ],
)
@pytest.mark.asyncio
async def test_upload_rejects_video_evidence_inconsistent_with_object_path_before_storage_or_persistence(
    monkeypatch: pytest.MonkeyPatch,
    video_presence: str,
    include_video: bool,
    video_offset_ms: int | None,
) -> None:
    object_store = Mock()
    object_store.save = AsyncMock(return_value="synthetic-object-ref")
    monkeypatch.setattr(router, "_get_object_store", Mock(return_value=object_store))
    monkeypatch.setattr(router, "_get_queue", Mock())
    create_engine = Mock(
        side_effect=AssertionError("invalid metadata must be rejected before persistence")
    )
    monkeypatch.setattr(router, "create_engine", create_engine)
    audio = UploadFile(filename="synthetic-audio.webm", file=BytesIO(b"audio"))
    video = (
        UploadFile(filename="synthetic-video.webm", file=BytesIO(b"video"))
        if include_video
        else None
    )
    metadata = _payload(video_presence=video_presence)
    if video_offset_ms is not None:
        metadata["video_offset_ms"] = video_offset_ms

    with pytest.raises(HTTPException) as error:
        await router.upload_recording(
            audio=audio,
            video=video,
            data=json.dumps(metadata),
            user=type("User", (), {"id": "synthetic-user"})(),
        )

    assert error.value.status_code == 422
    object_store.save.assert_not_awaited()
    create_engine.assert_not_called()


@pytest.mark.asyncio
async def test_upload_checks_meeting_owner_before_writing_any_media(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An authenticated non-owner cannot cause object storage writes for a foreign meeting."""
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.infra.models import Meeting

    foreign_meeting = Meeting(
        id="meeting-private-synthetic",
        meet_link=None,
        title=None,
        origin="manual",
        process_state="recording",
        created_by="actual-owner",
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
    session.get = AsyncMock(return_value=foreign_meeting)  # type: ignore[attr-defined]
    engine = AsyncMock()
    store = Mock()
    store.save = AsyncMock(return_value="private/staged-object")
    queue = Mock()
    queue.connect = AsyncMock()
    queue.publish = AsyncMock()
    queue.disconnect = AsyncMock()
    monkeypatch.setattr(router, "_get_object_store", Mock(return_value=store))
    monkeypatch.setattr(router, "_get_queue", Mock(return_value=queue))
    monkeypatch.setattr(router, "create_engine", Mock(return_value=engine))
    monkeypatch.setattr(router, "create_session_factory", Mock(return_value=Mock(return_value=session)))
    monkeypatch.setattr(
        router,
        "process_ingestion",
        AsyncMock(return_value=(SimpleNamespace(id="synthetic-recording", process_state="recording"), True)),
    )
    monkeypatch.setattr(
        router, "record_transition", AsyncMock(return_value=SimpleNamespace(successful=True))
    )
    audio = UploadFile(filename="synthetic.webm", file=BytesIO(b"synthetic media"))

    with pytest.raises(HTTPException) as error:
        await router.upload_recording(
            audio=audio,
            video=None,
            data=json.dumps(
                _payload(
                    meeting_id=foreign_meeting.id,
                    capture_origin="web_upload",
                    video_presence="absent",
                )
            ),
            user=SimpleNamespace(id="requesting-owner", is_sales=True),
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Meeting not found"
    store.save.assert_not_awaited()
    router.process_ingestion.assert_not_awaited()
