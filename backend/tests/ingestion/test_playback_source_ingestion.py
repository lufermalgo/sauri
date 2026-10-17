"""RED contract tests for explicit playback-source capture metadata."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from app.ingestion import router
from app.ingestion.schemas import IngestionData


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
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
    def storage_must_not_be_initialized():
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
