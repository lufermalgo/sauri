"""Local status, real account details and extension pairing."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.auth.dependencies import get_current_user
from app.auth.local import extension_paired, local_cookie_header, local_mode, local_token, mark_extension_paired
from app.auth.schemas import AuthenticatedUser
from app.infra.database import create_engine, create_session_factory
from app.infra.http_security import EXTENSION_NOT_ALLOWED, extension_origins
from app.local.inflight import count_processing


def require_local() -> None:
    if not local_mode():
        raise HTTPException(status_code=404, detail="local_mode_disabled")


router = APIRouter(prefix="/api/v1/local", tags=["local"], dependencies=[Depends(require_local)])
LocalUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


@router.get("/status")
async def local_status(request: Request, response: Response, user: LocalUser) -> dict[str, object]:
    engine = create_engine()
    try:
        async with create_session_factory(engine)() as session:
            processing = await count_processing(session)
    finally:
        await engine.dispose()
    response.headers["Cache-Control"] = "no-store"
    if request.headers.get("sec-fetch-site") == "same-origin":
        response.headers["Set-Cookie"] = local_cookie_header()
    return {
        "ready": True,
        "processing": processing,
        "version": request.app.version,
        "mode": "local",
        "extension_paired": extension_paired(),
    }


@router.get("/me")
async def local_me(response: Response, user: LocalUser) -> AuthenticatedUser:
    response.headers["Cache-Control"] = "no-store"
    return user


@router.post("/pair")
async def pair(request: Request, response: Response) -> dict[str, str]:
    if request.headers.get("origin") not in extension_origins(local=True):
        raise HTTPException(status_code=403, detail=EXTENSION_NOT_ALLOWED)
    response.headers["Cache-Control"] = "no-store"
    token = local_token()
    mark_extension_paired()
    return {"token": token}
