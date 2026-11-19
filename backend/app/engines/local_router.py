"""Authenticated proxy of the local-model routes of ``host-engine`` (hardware, catalog, install, jobs).

The target is fixed: every route below maps to one host route built from a template, with an id that
already matched the catalog or job-id alphabet. No query string, header or URL from the request is forwarded
(nor any body, except the validated fields of the two custom-model routes below), so a caller cannot steer
the call elsewhere (no SSRF) and cannot reach the secret or provider routes of the host. The management token
stays inside ``host_client`` and no key or secret travels through here: these routes carry model ids and
download progress only.

``POST /adopt`` asks the host to recognize models that are already on this Mac (installed by hand); it takes
no body and nothing from the request reaches the host. It returns a job like the other long operations.

``POST /custom/resolve`` and ``POST /custom/install`` (a model from a public Hugging Face repository) are the only
routes with a body. It is validated here (exactly the documented fields, bounded strings) and rebuilt from those
fields before it is sent; the host validates it again and never takes a URL, size or hash from it.

Installs, verifications and adoptions run as host jobs. The host answers ``202`` at once and the portal polls
``GET /jobs/{id}``: each poll is a short, independent call with its own timeout, so no connection is held
open and a slow download cannot tie up the API.

A host refusal keeps its status and its stable code, reported in this API's error shape
(``{"detail": "<code>", ...figures}``): the user needs figures such as the space an install requires or
the processes that use a model. Only scalar figures and short lists of words are relayed.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, Path, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth.authorization import require_sales
from app.auth.schemas import AuthenticatedUser
from app.engines.host_client import CUSTOM_TIMEOUT_S, HostClient, HostError, get_host_client
from app.engines.router import get_session
from app.infra.http_errors import SafeErrorRoute, api_error

router = APIRouter(prefix="/api/v1/engines/local", tags=["engines"], route_class=SafeErrorRoute)

AuthorizedUser = Annotated[AuthenticatedUser, Depends(require_sales(get_session))]
Host = Annotated[HostClient, Depends(get_host_client)]
# The catalog's id alphabet and the host's job-id format: nothing else can enter a host path.
ModelId = Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
JobId = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]

HOST_UNAVAILABLE: Final = "host_unavailable"
_EXTRA_NAME: Final = re.compile(r"[a-z][a-z_]{0,31}")
_MAX_CODE_CHARS: Final = 64
_MAX_EXTRA_ITEMS: Final = 16
_MAX_EXTRA_CHARS: Final = 128


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, bool | int) or (isinstance(value, str) and len(value) <= _MAX_EXTRA_CHARS)


def _failure(status_code: int, body: dict[str, Any] | None) -> JSONResponse:
    """The host's refusal in this API's error shape; unknown shapes become a generic 502."""
    error = (body or {}).get("error")
    code = error.get("code") if isinstance(error, dict) else None
    if (
        not isinstance(error, dict)
        or not isinstance(code, str)
        or not code.isascii()
        or not 0 < len(code) <= _MAX_CODE_CHARS
        or (status_code >= 500 and status_code not in (503, 507))
    ):
        return JSONResponse({"detail": "host_error"}, status_code=status.HTTP_502_BAD_GATEWAY)
    content: dict[str, Any] = {"detail": code}
    for name, value in error.items():
        if name in ("code", "detail") or not _EXTRA_NAME.fullmatch(name):
            continue
        if _scalar(value) or (
            isinstance(value, list) and len(value) <= _MAX_EXTRA_ITEMS and all(_scalar(item) for item in value)
        ):
            content[name] = value
    return JSONResponse(content, status_code=status_code)


CustomProcess = Literal["transcription", "summary"]


class CustomResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    process: CustomProcess
    source: str = Field(min_length=1, max_length=512)


class CustomInstallIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    process: CustomProcess
    repo: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    file: str = Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9._+/-]+$")

    @field_validator("file")
    @classmethod
    def _relative_path(cls, value: str) -> str:
        if any(segment in ("", ".", "..") for segment in value.split("/")):
            raise ValueError("invalid_file")
        return value


async def _forward(host: HostClient, method: str, path: str, payload: dict[str, Any] | None = None) -> Response:
    try:
        if payload is None:
            status_code, body = await host.local(method, path)
        else:
            status_code, body = await host.local(method, path, json=payload, timeout=CUSTOM_TIMEOUT_S)
    except HostError:
        raise api_error(status.HTTP_503_SERVICE_UNAVAILABLE, HOST_UNAVAILABLE) from None
    if status_code >= 400:
        response: Response = _failure(status_code, body)
    elif status_code == status.HTTP_204_NO_CONTENT or body is None:
        response = Response(status_code=status_code)
    else:
        response = JSONResponse(body, status_code=status_code)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/hardware")
async def get_hardware(user: AuthorizedUser, host: Host) -> Response:
    return await _forward(host, "GET", "/v1/hardware")


@router.get("/models")
async def list_local_models(user: AuthorizedUser, host: Host) -> Response:
    return await _forward(host, "GET", "/v1/local/models")


@router.post("/adopt", status_code=status.HTTP_202_ACCEPTED)
async def adopt_models(user: AuthorizedUser, host: Host) -> Response:
    return await _forward(host, "POST", "/v1/local/adopt")


@router.post("/models/{model_id}/install", status_code=status.HTTP_202_ACCEPTED)
async def install_model(model_id: ModelId, user: AuthorizedUser, host: Host) -> Response:
    return await _forward(host, "POST", f"/v1/local/models/{model_id}/install")


@router.post("/custom/resolve")
async def resolve_custom_model(request: CustomResolveIn, user: AuthorizedUser, host: Host) -> Response:
    return await _forward(host, "POST", "/v1/local/custom/resolve", request.model_dump())


@router.post("/custom/install", status_code=status.HTTP_202_ACCEPTED)
async def install_custom_model(request: CustomInstallIn, user: AuthorizedUser, host: Host) -> Response:
    return await _forward(host, "POST", "/v1/local/custom/install", request.model_dump())


@router.post("/models/{model_id}/verify", status_code=status.HTTP_202_ACCEPTED)
async def verify_model(model_id: ModelId, user: AuthorizedUser, host: Host) -> Response:
    return await _forward(host, "POST", f"/v1/local/models/{model_id}/verify")


@router.delete("/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_model(model_id: ModelId, user: AuthorizedUser, host: Host) -> Response:
    return await _forward(host, "DELETE", f"/v1/local/models/{model_id}")


@router.get("/jobs/{job_id}")
async def get_job(job_id: JobId, user: AuthorizedUser, host: Host) -> Response:
    return await _forward(host, "GET", f"/v1/local/jobs/{job_id}")


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: JobId, user: AuthorizedUser, host: Host) -> Response:
    return await _forward(host, "POST", f"/v1/local/jobs/{job_id}/cancel")
