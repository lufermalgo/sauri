"""Application-wide error handlers registered by ``create_app`` never expose internals."""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.main import create_app


class _Payload(BaseModel):
    count: int


def _app() -> FastAPI:
    application = create_app()

    @application.get("/_boom")
    async def boom() -> None:
        raise RuntimeError("db password is hunter2-do-not-leak")

    @application.get("/_teapot")
    async def teapot() -> None:
        raise HTTPException(status_code=418, detail="short and stout")

    @application.post("/_validate")
    async def validate(payload: _Payload) -> dict[str, int]:
        return {"count": payload.count}

    return application


@pytest.fixture
def client() -> TestClient:
    return TestClient(_app(), raise_server_exceptions=False)


def test_unhandled_exception_returns_generic_body_with_request_id(client: TestClient) -> None:
    response = client.get("/_boom")
    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "internal_error"
    assert len(body["request_id"]) == 32
    assert "hunter2" not in response.text
    assert "Traceback" not in response.text
    assert response.headers["x-content-type-options"] == "nosniff"


def test_unhandled_exception_is_logged_with_traceback_and_same_request_id(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="app.infra.http_errors"):
        response = client.get("/_boom?token=secret-in-query")
    request_id = response.json()["request_id"]
    record = next(r for r in caplog.records if request_id in r.getMessage())
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None and record.exc_info[0] is RuntimeError
    assert "path=/_boom" in record.getMessage()
    assert "secret-in-query" not in record.getMessage()


def test_request_ids_are_unique(client: TestClient) -> None:
    assert client.get("/_boom").json()["request_id"] != client.get("/_boom").json()["request_id"]


def test_http_exception_semantics_are_unchanged(client: TestClient) -> None:
    response = client.get("/_teapot")
    assert response.status_code == 418
    assert response.json() == {"detail": "short and stout"}
    assert client.get("/missing").status_code == 404


def test_validation_error_is_422_without_input_or_ctx(client: TestClient) -> None:
    response = client.post("/_validate", json={"count": "super-secret-value"})
    assert response.status_code == 422
    body = response.json()
    assert body["detail"] == "invalid_request"
    assert body["errors"] == [{"loc": ["body", "count"], "type": "int_parsing"}]
    assert "super-secret-value" not in response.text
    assert "input" not in response.text
    assert "ctx" not in response.text


def test_validation_error_for_malformed_json_does_not_echo_the_body(client: TestClient) -> None:
    response = client.post(
        "/_validate", content=b'{"count": secret-raw-body', headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert "secret-raw-body" not in response.text
