"""Serve only the local object named by a valid, short-lived capability."""

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.infra.object_store import create_object_store
from app.infra.object_store_fs import FilesystemObjectStore
from app.infra.secrets import SecretUnavailableError
from app.media.tokens import verify_media_token

router = APIRouter(prefix="/api/v1/media", tags=["media"])


@router.get("/{token}")
async def read_media(token: str) -> FileResponse:
    if os.environ.get("OBJECT_STORE_KIND", "s3") != "filesystem":
        raise HTTPException(status_code=404, detail="media_unavailable")
    try:
        claims = verify_media_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="invalid_media_token") from exc
    except SecretUnavailableError as exc:
        raise HTTPException(status_code=503, detail="media_unavailable") from exc
    store = create_object_store()
    assert isinstance(store, FilesystemObjectStore)
    try:
        path = store.local_path(claims["key"])
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="invalid_media_token") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="media_not_found")
    return FileResponse(
        path, media_type=claims["ct"], filename=claims["filename"] or path.name,
        content_disposition_type=claims["disp"],
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
