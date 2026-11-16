"""Host service routes of the ChatGPT-plan sign-in and its model list; HTTP is scripted, no OpenAI call is made."""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType

import chatgpt_auth
import pytest
from conftest import MANAGEMENT_TOKEN
from fastapi import FastAPI
from fastapi.testclient import TestClient
from providers import ProviderService
from providers import build_router as providers_router
from sauri_engine_common.chatgpt_login import ACCESS_REF, REFRESH_REF, ChatGptLogin
from sauri_engine_common.secrets import FileSecretStore, SecretRecord

from tests.engine_common.chatgpt_support import ACCOUNT, EMAIL, NOW, Clock, ScriptedHttp, fake_jwt, reply

ACCESS = fake_jwt(exp=NOW + 3600)
REFRESH = "refresh-synthetic-1"
AUTH = {"Authorization": f"Bearer {MANAGEMENT_TOKEN}"}
BASE = "https://chatgpt.com/backend-api/codex"
MODELS = {"models": [{"slug": "gpt-5", "display_name": "GPT-5", "priority": 1}, {"slug": "gpt-5-mini", "priority": 2}]}
SECRETS = (ACCESS, REFRESH, "device-auth-synthetic", "grant-code-synthetic", "verifier-synthetic")


@pytest.fixture
def store(tmp_path: Path) -> FileSecretStore:
    return FileSecretStore(tmp_path / "secrets")


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def http() -> ScriptedHttp:
    return ScriptedHttp(
        {
            "POST /api/accounts/deviceauth/usercode": reply(
                200, {"user_code": "ABCD-1234", "device_auth_id": "device-auth-synthetic", "interval": 5}
            ),
            "POST /api/accounts/deviceauth/token": reply(
                200, {"authorization_code": "grant-code-synthetic", "code_verifier": "verifier-synthetic"}
            ),
            "POST /oauth/token": reply(200, {"access_token": ACCESS, "refresh_token": REFRESH}),
            "GET /backend-api/codex/models": reply(200, MODELS),
        }  # type: ignore[arg-type]
    )


@pytest.fixture
def client(store: FileSecretStore, http: ScriptedHttp, clock: Clock, tmp_path: Path) -> TestClient:
    login = ChatGptLogin(store, http, clock=clock, lock_path=tmp_path / "lock")

    async def get_login() -> ChatGptLogin:
        return login

    async def get_store() -> FileSecretStore:
        return store

    def require_token() -> None:
        return None

    app = FastAPI()
    app.include_router(chatgpt_auth.build_router(get_login, require_token))
    service = ProviderService(chatgpt_http=http, models_timeout_s=2.0, probe_timeout_s=2.0)
    app.include_router(providers_router(get_store, require_token, service, get_login))  # type: ignore[arg-type]
    return TestClient(app, raise_server_exceptions=False)


def connect(store: FileSecretStore) -> None:
    store.put(
        REFRESH_REF,
        SecretRecord(
            json.dumps({"refresh_token": REFRESH, "account_id": ACCOUNT, "email": EMAIL, "plan": "plus"}),
            "https://auth.openai.com",
        ),
    )
    store.put(
        ACCESS_REF, SecretRecord(json.dumps({"access_token": ACCESS, "expires_at": NOW + 3600}), "https://chatgpt.com")
    )


def models_body(**extra: object) -> dict[str, object]:
    return {
        "kind": "chatgpt_plan",
        "transport": "chatgpt-responses",
        "base_url": BASE,
        "capability": "summary",
        **extra,
    }


def test_the_sign_in_runs_through_the_routes_without_exposing_a_token(client: TestClient, clock: Clock) -> None:
    assert client.get("/v1/oauth/chatgpt/status").json()["state"] == "disconnected"
    started = client.post("/v1/oauth/chatgpt/start")
    assert started.status_code == 200
    assert started.json()["pending"] == {
        "user_code": "ABCD-1234",
        "verification_url": "https://auth.openai.com/codex/device",
        "expires_at": NOW + 900,
        "interval_s": 5,
        "slow_down": False,
    }
    clock.now += 5
    polled = client.post("/v1/oauth/chatgpt/poll")
    assert polled.json() == {"state": "connected", "account": EMAIL, "plan": "plus", "pending": None, "error": None}
    again = client.get("/v1/oauth/chatgpt/status")
    for response in (started, polled, again):
        assert not any(secret in response.text for secret in SECRETS)
    assert client.post("/v1/oauth/chatgpt/logout").status_code == 204
    assert client.get("/v1/oauth/chatgpt/status").json()["state"] == "disconnected"


def test_a_rate_limited_start_answers_429_with_the_error_shape(client: TestClient, http: ScriptedHttp) -> None:
    http.script["POST /api/accounts/deviceauth/usercode"] = reply(429, {}, retry_after="20")
    response = client.post("/v1/oauth/chatgpt/start")
    assert response.status_code == 429
    assert response.json()["error"] == {
        "code": "provider_rate_limited", "retryable": True, "retry_after_s": 20, "cause": "start_rate_limited",
    }  # fmt: skip


def test_models_are_listed_from_the_plan_with_its_first_as_starter(client: TestClient, store: FileSecretStore) -> None:
    connect(store)
    response = client.post("/v1/providers/models", json=models_body())
    assert response.status_code == 200, response.text
    assert response.json()["models"] == [{"id": "gpt-5", "name": "GPT-5"}, {"id": "gpt-5-mini", "name": "gpt-5-mini"}]
    assert response.json()["starter"] == "gpt-5" and response.json()["cached"] is False
    assert not any(secret in response.text for secret in SECRETS)


def test_the_connection_test_lists_models_and_needs_no_key(client: TestClient, store: FileSecretStore) -> None:
    connect(store)
    result = client.post("/v1/providers/probe", json=models_body()).json()
    assert result["ok"] is True and result["json_schema_ok"] is None


def test_models_without_a_sign_in_ask_for_one(client: TestClient) -> None:
    response = client.post("/v1/providers/models", json=models_body())
    assert response.status_code == 502  # never 401: the API client reads that as a bad management token
    assert response.json()["error"]["code"] == "provider_auth" and response.json()["error"]["cause"] == "login_required"
    probe = client.post("/v1/providers/probe", json=models_body()).json()
    assert (probe["ok"], probe["error_class"], probe["cause"]) == (False, "provider_auth", "login_required")


def test_a_refused_refresh_clears_the_sign_in_and_the_list_fails_cleanly(
    client: TestClient, store: FileSecretStore, http: ScriptedHttp, clock: Clock
) -> None:
    connect(store)
    clock.now += 4000  # the stored token expired
    http.script["POST /oauth/token"] = reply(400, {"error": "invalid_grant"})
    response = client.post("/v1/providers/models", json=models_body())
    assert response.status_code == 502 and response.json()["error"]["cause"] == "login_required"
    status = client.get("/v1/oauth/chatgpt/status").json()
    assert (status["state"], status["error"]) == ("disconnected", "session_expired")


def test_the_models_call_only_goes_to_the_plan_host(
    client: TestClient, store: FileSecretStore, http: ScriptedHttp
) -> None:
    connect(store)
    client.post("/v1/providers/models", json=models_body())
    assert [item.url.split("/")[2] for item in http.sent] == ["chatgpt.com"]


# --- wiring in the real host app -------------------------------------------------------------------------------


def test_the_host_app_protects_the_sign_in_routes(host: ModuleType) -> None:
    client = TestClient(host.app)
    for method, path in (("get", "/v1/oauth/chatgpt/status"), ("post", "/v1/oauth/chatgpt/start")):
        assert getattr(client, method)(path).status_code == 401
    assert client.get("/v1/oauth/chatgpt/status", headers=AUTH).json()["state"] == "disconnected"
