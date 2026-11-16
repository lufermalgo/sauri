"""The shared error contract never echoes submitted input or exception text."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ConfigDict, Field

from app.infra.http_errors import (
    SafeErrorRoute,
    api_error,
    request_validation_exception_handler,
    sanitized_validation_errors,
)


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=5)
    count: int = Field(ge=0)


def _app(*, safe_route: bool = True, global_handler: bool = False) -> FastAPI:
    router = APIRouter(route_class=SafeErrorRoute) if safe_route else APIRouter()

    @router.post("/echo/{item_id}")
    async def echo(item_id: int, body: _Body) -> dict[str, str]:
        return {"name": body.name}

    @router.get("/missing")
    async def missing() -> None:
        raise api_error(404, "not_found")

    application = FastAPI()
    application.include_router(router)
    if global_handler:
        application.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    return application


async def _post(application: FastAPI, path: str, **kwargs: object) -> tuple[int, dict[str, object], str]:
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://t") as client:
        response = await client.post(path, **kwargs)  # type: ignore[arg-type]
    return response.status_code, response.json(), response.text


async def test_default_fastapi_422_echoes_the_input_which_is_why_the_route_class_exists() -> None:
    status, _, text = await _post(
        _app(safe_route=False), "/echo/1", json={"name": "private-value-123", "count": 1}
    )
    assert status == 422
    assert "private-value-123" in text


async def test_safe_route_422_reports_locations_and_rules_only() -> None:
    status, body, text = await _post(
        _app(), "/echo/abc-secret",
        json={"name": "private-value-123", "count": "secret-count", "smuggled-key": "x"},
    )

    assert status == 422
    assert body["detail"] == "invalid_request"
    for leaked in ("private-value-123", "secret-count", "smuggled-key", "abc-secret", "input", "ctx", "msg"):
        assert leaked not in text
    assert {"loc": ["body", "name"], "type": "string_too_long"} in body["errors"]  # type: ignore[operator]
    assert {"loc": ["path", "item_id"], "type": "int_parsing"} in body["errors"]  # type: ignore[operator]
    assert {"loc": ["body"], "type": "extra_forbidden"} in body["errors"]  # type: ignore[operator]


async def test_malformed_json_422_does_not_echo_the_document() -> None:
    status, body, text = await _post(
        _app(), "/echo/1", content='{"name": "private-doc", ', headers={"content-type": "application/json"}
    )
    assert status == 422
    assert body["detail"] == "invalid_request"
    assert "private-doc" not in text


async def test_global_handler_gives_the_same_body_for_routers_without_the_route_class() -> None:
    status, body, text = await _post(
        _app(safe_route=False, global_handler=True), "/echo/1", json={"name": "private-value-123", "count": 1}
    )
    assert status == 422
    assert body["detail"] == "invalid_request"
    assert "private-value-123" not in text


async def test_api_error_body_is_only_the_machine_code() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as client:
        response = await client.get("/missing")
    assert response.status_code == 404
    assert response.json() == {"detail": "not_found"}


def test_error_list_is_bounded() -> None:
    errors = [{"loc": ("body", "a"), "type": "missing"}] * 500
    assert len(sanitized_validation_errors(errors)) == 20
