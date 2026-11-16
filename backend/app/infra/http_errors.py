"""Generic, stable HTTP error contract shared by the API routers.

Every error body is ``{"detail": "<machine_code>"}`` (validation errors add an
``errors`` list of locations and rule names). Exceptions, Pydantic internals and the
submitted ``input`` are never interpolated into a response: FastAPI's default 422
echoes the offending value, which reflects attacker-controlled text back and can leak
fragments of private payloads into logs and proxies.

Routers opt in with ``APIRouter(route_class=SafeErrorRoute)``, which replaces the 422
response for that router only. ``request_validation_exception_handler`` is the same
behaviour as an application-wide handler; ``app.main`` may register it with
``app.add_exception_handler(RequestValidationError, request_validation_exception_handler)``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Coroutine, Mapping, Sequence
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

INVALID_REQUEST = "invalid_request"
UNAUTHORIZED = "unauthorized"
FORBIDDEN = "forbidden"
NOT_FOUND = "not_found"
CONFLICT = "conflict"
PAYLOAD_TOO_LARGE = "payload_too_large"
UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"

_SAFE_LOC_PART = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_MAX_REPORTED_ERRORS = 20


def api_error(
    status_code: int, code: str, headers: Mapping[str, str] | None = None
) -> HTTPException:
    """Build an HTTPException whose body is only the stable machine code."""
    return HTTPException(
        status_code=status_code, detail=code, headers=dict(headers) if headers else None
    )


def _safe_location(error: Mapping[str, Any]) -> list[str | int]:
    """Keep field names and indexes only; never a key chosen by the caller."""
    location = list(error.get("loc", ()))
    if error.get("type") == "extra_forbidden":
        location = location[:-1]  # the last element is the unknown key the caller sent
    return [
        part
        for part in location
        if isinstance(part, int) or (isinstance(part, str) and _SAFE_LOC_PART.match(part))
    ]


def sanitized_validation_errors(errors: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Reduce Pydantic errors to location and rule name, dropping msg, input and ctx."""
    return [
        {"loc": _safe_location(error), "type": str(error.get("type", "invalid"))}
        for error in errors[:_MAX_REPORTED_ERRORS]
    ]


def validation_error_response(exc: RequestValidationError) -> JSONResponse:
    """A 422 response that never echoes the submitted input."""
    return JSONResponse(
        status_code=422,
        content={"detail": INVALID_REQUEST, "errors": sanitized_validation_errors(exc.errors())},
    )


async def request_validation_exception_handler(
    _request: Request, exc: Exception
) -> JSONResponse:
    """Application-wide handler for ``RequestValidationError`` (see module docstring)."""
    assert isinstance(exc, RequestValidationError)
    return validation_error_response(exc)


class SafeErrorRoute(APIRoute):
    """Route class whose request-validation failures use the sanitized 422 body."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError as exc:
                return validation_error_response(exc)

        return handler


def set_page_headers(
    response: Response, request: Request, total: int, limit: int, offset: int, returned: int
) -> None:
    """Describe a page of a bare-list response without changing the body shape."""
    response.headers["X-Total-Count"] = str(total)
    if offset + returned < total:
        next_url = request.url.include_query_params(limit=limit, offset=offset + limit)
        response.headers["Link"] = f'<{next_url}>; rel="next"'
