"""ChatGPT-plan sign-in: device code, polling states, refresh single-flight, refusal and secrecy. No network."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import pytest
from sauri_engine_common import chatgpt_login
from sauri_engine_common.chatgpt_login import ACCESS_REF, CLIENT_ID, REFRESH_REF, ChatGptLogin
from sauri_engine_common.external.allowlist_http import AllowlistedHttp
from sauri_engine_common.external.errors import ProviderError
from sauri_engine_common.secrets import FileSecretStore, SecretRecord

from tests.engine_common.chatgpt_support import ACCOUNT, EMAIL, NOW, Clock, ScriptedHttp, Sent, fake_jwt, reply

ACCESS_1 = fake_jwt(exp=NOW + 3600)
ACCESS_2 = fake_jwt(exp=NOW + 7200)
REFRESH_1 = "refresh-synthetic-1"
REFRESH_2 = "refresh-synthetic-2"
USERCODE = "POST /api/accounts/deviceauth/usercode"
DEVICE_TOKEN = "POST /api/accounts/deviceauth/token"
OAUTH = "POST /oauth/token"
SECRETS = (
    ACCESS_1,
    ACCESS_2,
    REFRESH_1,
    REFRESH_2,
    "device-auth-synthetic",
    "grant-code-synthetic",
    "verifier-synthetic",
)


def device_reply() -> object:
    return reply(200, {"user_code": "ABCD-1234", "device_auth_id": "device-auth-synthetic", "interval": 5})


GRANT = reply(200, {"authorization_code": "grant-code-synthetic", "code_verifier": "verifier-synthetic"})


def tokens(access: str = ACCESS_1, refresh: str | None = REFRESH_1) -> object:
    return reply(200, {"access_token": access, "refresh_token": refresh} if refresh else {"access_token": access})


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(tmp_path: Path) -> FileSecretStore:
    return FileSecretStore(tmp_path / "secrets")


def make(store: FileSecretStore, http: ScriptedHttp, clock: Clock, tmp_path: Path) -> ChatGptLogin:
    return ChatGptLogin(store, http, clock=clock, lock_path=tmp_path / "locks" / "login.lock")


@pytest.fixture
def http() -> ScriptedHttp:
    return ScriptedHttp({USERCODE: device_reply(), OAUTH: tokens()})  # type: ignore[dict-item]


@pytest.fixture
def login(store: FileSecretStore, http: ScriptedHttp, clock: Clock, tmp_path: Path) -> ChatGptLogin:
    return make(store, http, clock, tmp_path)


def connect_directly(store: FileSecretStore, *, access: str = ACCESS_1, expires_at: float = NOW + 3600) -> None:
    store.put(
        REFRESH_REF,
        SecretRecord(
            json.dumps({"refresh_token": REFRESH_1, "account_id": ACCOUNT, "email": EMAIL, "plan": "plus"}),
            "https://auth.openai.com",
        ),
    )
    store.put(
        ACCESS_REF,
        SecretRecord(json.dumps({"access_token": access, "expires_at": expires_at}), "https://chatgpt.com"),
    )


# --- device sign-in -----------------------------------------------------------------------------------------


async def test_start_returns_the_code_the_address_and_the_expiry(login: ChatGptLogin, http: ScriptedHttp) -> None:
    status = await login.start()
    assert status["state"] == "pending"
    pending = status["pending"]
    assert pending["user_code"] == "ABCD-1234"
    assert pending["verification_url"] == "https://auth.openai.com/codex/device"
    assert pending["expires_at"] == NOW + 15 * 60
    sent = http.calls("POST", "/api/accounts/deviceauth/usercode")[0]
    assert sent.json() == {"client_id": CLIENT_ID} and sent.url.startswith("https://auth.openai.com/")
    assert "device-auth-synthetic" not in json.dumps(status)  # the device id never leaves the host


async def test_start_rate_limited_is_retryable(login: ChatGptLogin, http: ScriptedHttp) -> None:
    http.script[USERCODE] = reply(429, {}, retry_after="30")
    with pytest.raises(ProviderError) as caught:
        await login.start()
    assert (caught.value.code, caught.value.retryable, caught.value.retry_after_s) == (
        "provider_rate_limited",
        True,
        30,
    )


async def test_poll_waits_while_the_user_has_not_approved(
    login: ChatGptLogin, http: ScriptedHttp, clock: Clock
) -> None:
    http.script[DEVICE_TOKEN] = reply(403)
    await login.start()
    assert (await login.poll())["state"] == "pending" and not http.calls("POST", "/api/accounts/deviceauth/token")
    clock.now += 5  # the interval passed: one upstream check
    assert (await login.poll())["state"] == "pending"
    assert (await login.poll())["state"] == "pending"  # too soon again: no second check
    assert len(http.calls("POST", "/api/accounts/deviceauth/token")) == 1
    http.script[DEVICE_TOKEN] = reply(404)
    clock.now += 5
    assert (await login.poll())["state"] == "pending" and len(http.calls("POST", "/api/accounts/deviceauth/token")) == 2


@pytest.mark.parametrize("answer", [reply(429), reply(400, {"error": "slow_down"})], ids=["429", "slow_down"])
async def test_slow_down_lengthens_the_interval(
    login: ChatGptLogin, http: ScriptedHttp, clock: Clock, answer: object
) -> None:
    http.script[DEVICE_TOKEN] = answer  # type: ignore[assignment]
    await login.start()
    clock.now += 5
    status = await login.poll()
    assert status["state"] == "pending" and status["pending"]["slow_down"] is True
    assert status["pending"]["interval_s"] == 10
    clock.now += 6  # shorter than the new interval: no upstream check
    await login.poll()
    assert len(http.calls("POST", "/api/accounts/deviceauth/token")) == 1


async def test_code_expires_by_the_clock(login: ChatGptLogin, http: ScriptedHttp, clock: Clock) -> None:
    await login.start()
    clock.now += 15 * 60
    status = await login.poll()
    assert (status["state"], status["error"], status["pending"]) == ("disconnected", "code_expired", None)
    assert not http.calls("POST", "/api/accounts/deviceauth/token")


async def test_code_expires_upstream(login: ChatGptLogin, http: ScriptedHttp, clock: Clock) -> None:
    http.script[DEVICE_TOKEN] = reply(400, {"error": {"code": "expired_token"}})
    await login.start()
    clock.now += 5
    assert (await login.poll())["error"] == "code_expired"


async def test_denied_ends_the_sign_in(login: ChatGptLogin, http: ScriptedHttp, clock: Clock) -> None:
    http.script[DEVICE_TOKEN] = reply(400, {"error": "access_denied"})
    await login.start()
    clock.now += 5
    status = await login.poll()
    assert (status["state"], status["error"]) == ("disconnected", "access_denied")


async def test_approval_connects_and_stores_tokens_only_in_the_store(
    login: ChatGptLogin, http: ScriptedHttp, clock: Clock, store: FileSecretStore
) -> None:
    http.script[DEVICE_TOKEN] = GRANT
    await login.start()
    clock.now += 5
    status = await login.poll()
    assert status == {"state": "connected", "account": EMAIL, "plan": "plus", "pending": None, "error": None}
    exchange = http.calls("POST", "/oauth/token")[0].form()
    assert exchange == {
        "grant_type": "authorization_code",
        "code": "grant-code-synthetic",
        "redirect_uri": "https://auth.openai.com/deviceauth/callback",
        "client_id": CLIENT_ID,
        "code_verifier": "verifier-synthetic",
    }
    assert json.loads(store.get(REFRESH_REF).key)["refresh_token"] == REFRESH_1
    assert json.loads(store.get(ACCESS_REF).key)["access_token"] == ACCESS_1
    assert not any(secret in json.dumps(status) for secret in SECRETS)
    credentials = await login.credentials()
    assert credentials.headers() == {
        "authorization": f"Bearer {ACCESS_1}",
        "chatgpt-account-id": ACCOUNT,
        "originator": "sauri",
        "user-agent": "sauri-chatgpt-plan/1",
    }
    assert len(http.calls("POST", "/oauth/token")) == 1  # a fresh token is not refreshed


async def test_status_shows_the_account_id_when_the_token_names_no_email(
    login: ChatGptLogin, http: ScriptedHttp, clock: Clock
) -> None:
    http.script[DEVICE_TOKEN] = GRANT
    http.script[OAUTH] = tokens(fake_jwt(exp=NOW + 3600, email=None, plan=None))
    await login.start()
    clock.now += 5
    status = await login.poll()
    assert (status["state"], status["account"], status["plan"]) == ("connected", ACCOUNT, None)


async def test_a_token_without_an_account_is_not_kept(
    login: ChatGptLogin, http: ScriptedHttp, clock: Clock, store: FileSecretStore
) -> None:
    http.script[DEVICE_TOKEN] = GRANT
    http.script[OAUTH] = tokens(fake_jwt(exp=NOW + 3600, account=None))
    await login.start()
    clock.now += 5
    status = await login.poll()
    assert (status["state"], status["error"]) == ("disconnected", "login_failed")
    with pytest.raises(Exception):  # noqa: B017,PT011  (the store raises its own class)
        store.get(REFRESH_REF)


async def test_disconnect_forgets_the_account(login: ChatGptLogin, store: FileSecretStore) -> None:
    connect_directly(store)
    assert (await login.status())["state"] == "connected"
    await login.disconnect()
    assert (await login.status())["state"] == "disconnected"
    for ref in (REFRESH_REF, ACCESS_REF):
        with pytest.raises(Exception):  # noqa: B017,PT011
            store.get(ref)
    with pytest.raises(ProviderError) as caught:
        await login.credentials()
    assert (caught.value.code, caught.value.reason) == ("provider_auth", "login_required")


# --- refresh -------------------------------------------------------------------------------------------------


async def test_a_token_close_to_expiry_is_refreshed_and_the_new_refresh_token_is_stored(
    login: ChatGptLogin, http: ScriptedHttp, store: FileSecretStore, clock: Clock
) -> None:
    connect_directly(store, expires_at=NOW + 60)  # inside the 120 s skew
    http.script[OAUTH] = tokens(ACCESS_2, REFRESH_2)
    credentials = await login.credentials()
    assert credentials.token == ACCESS_2
    form = http.calls("POST", "/oauth/token")[0].form()
    assert form == {"grant_type": "refresh_token", "refresh_token": REFRESH_1, "client_id": CLIENT_ID}
    assert json.loads(store.get(REFRESH_REF).key)["refresh_token"] == REFRESH_2
    assert json.loads(store.get(ACCESS_REF).key)["access_token"] == ACCESS_2


async def test_refresh_keeps_the_old_refresh_token_when_the_answer_has_none(
    login: ChatGptLogin, http: ScriptedHttp, store: FileSecretStore
) -> None:
    connect_directly(store, expires_at=NOW + 10)
    http.script[OAUTH] = tokens(ACCESS_2, None)
    await login.credentials()
    assert json.loads(store.get(REFRESH_REF).key)["refresh_token"] == REFRESH_1


async def test_concurrent_callers_cause_one_refresh(store: FileSecretStore, clock: Clock, tmp_path: Path) -> None:
    connect_directly(store, expires_at=NOW + 10)

    async def slow(_sent: Sent) -> object:
        await asyncio.sleep(0.15)
        return tokens(ACCESS_2, REFRESH_2)

    http = ScriptedHttp({OAUTH: slow})  # type: ignore[dict-item]
    login = make(store, http, clock, tmp_path)
    results = await asyncio.gather(*(login.credentials() for _ in range(6)))
    assert {item.token for item in results} == {ACCESS_2}
    assert len(http.calls("POST", "/oauth/token")) == 1


async def test_two_processes_sharing_the_store_cause_one_refresh(
    store: FileSecretStore, clock: Clock, tmp_path: Path
) -> None:
    """The host service and the LLM gateway are two logins over the same records and the same lock file."""
    connect_directly(store, expires_at=NOW + 10)

    async def slow(_sent: Sent) -> object:
        await asyncio.sleep(0.15)
        return tokens(ACCESS_2, REFRESH_2)

    http = ScriptedHttp({OAUTH: slow})  # type: ignore[dict-item]
    host, gateway = make(store, http, clock, tmp_path), make(store, http, clock, tmp_path)
    first, second = await asyncio.gather(host.credentials(), gateway.credentials())
    assert first.token == second.token == ACCESS_2
    assert len(http.calls("POST", "/oauth/token")) == 1


async def test_renew_after_a_refused_token_refreshes_once_for_concurrent_callers(
    login: ChatGptLogin, http: ScriptedHttp, store: FileSecretStore
) -> None:
    connect_directly(store)  # still valid by its clock, but the API refused it
    http.script[OAUTH] = tokens(ACCESS_2, REFRESH_2)
    first, second = await asyncio.gather(login.renew(), login.renew())
    assert first.token == second.token == ACCESS_2
    assert len(http.calls("POST", "/oauth/token")) == 1


@pytest.mark.parametrize(
    "answer",
    [reply(400, {"error": "invalid_grant"}), reply(401), reply(400, {"error": {"code": "refresh_token_reused"}})],
    ids=["invalid_grant", "401", "reused"],
)
async def test_a_refused_refresh_clears_the_sign_in(
    login: ChatGptLogin, http: ScriptedHttp, store: FileSecretStore, answer: object
) -> None:
    connect_directly(store, expires_at=NOW + 10)
    http.script[OAUTH] = answer  # type: ignore[assignment]
    with pytest.raises(ProviderError) as caught:
        await login.credentials()
    assert (caught.value.code, caught.value.reason, caught.value.retryable) == (
        "provider_auth",
        "login_required",
        False,
    )
    status = await login.status()
    assert (status["state"], status["error"]) == ("disconnected", "session_expired")
    for ref in (REFRESH_REF, ACCESS_REF):
        with pytest.raises(Exception):  # noqa: B017,PT011
            store.get(ref)


@pytest.mark.parametrize(
    ("answer", "code"),
    [(reply(503), "provider_unavailable"), (reply(429, {}, retry_after="9"), "provider_rate_limited")],
    ids=["503", "429"],
)
async def test_a_failed_refresh_that_is_not_a_refusal_keeps_the_sign_in(
    login: ChatGptLogin, http: ScriptedHttp, store: FileSecretStore, answer: object, code: str
) -> None:
    connect_directly(store, expires_at=NOW + 10)
    http.script[OAUTH] = answer  # type: ignore[assignment]
    with pytest.raises(ProviderError) as caught:
        await login.credentials()
    assert caught.value.code == code and caught.value.retryable
    assert (await login.status())["state"] == "connected"


# --- secrecy and hosts ----------------------------------------------------------------------------------------


async def test_no_token_reaches_the_logs_or_any_representation(
    login: ChatGptLogin, http: ScriptedHttp, store: FileSecretStore, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    http.script[DEVICE_TOKEN] = [reply(403), GRANT]  # type: ignore[list-item]
    await login.start()
    clock.now += 5
    await login.poll()
    clock.now += 5
    assert (await login.poll())["state"] == "connected"
    clock.now += 4000
    http.script[OAUTH] = reply(400, {"error": "invalid_grant", "error_description": f"bad {REFRESH_1} {ACCESS_1}"})
    with pytest.raises(ProviderError) as caught:
        await login.credentials()
    for text in (caplog.text, repr(caught.value), str(caught.value), repr(login), repr(await login.status())):
        assert not any(secret in text for secret in SECRETS)
    clock.now = NOW
    connect_directly(store)
    assert ACCESS_1 not in repr(await login.credentials())


def test_the_module_never_reads_the_codex_cli_files() -> None:
    source = Path(chatgpt_login.__file__).read_text()
    assert "auth.json" not in source and 'home() / ".codex"' not in source


async def test_only_the_two_hosts_are_reachable() -> None:
    async def nowhere(_host: str, _port: int) -> list[str]:
        return []

    http = AllowlistedHttp(frozenset({"auth.openai.com", "chatgpt.com"}), resolver=nowhere)
    for url in (
        "https://evil.example.com/oauth/token",
        "https://chatgpt.com.evil.example.com/x",
        "http://chatgpt.com/x",
        "https://127.0.0.1/x",
        "https://user@chatgpt.com@evil.example.com/x",
    ):
        with pytest.raises(ProviderError) as caught:
            await http.request("GET", url, headers={}, allow_local=False, total_timeout_s=2)
        assert caught.value.reason in ("host_not_allowed", "invalid_url"), url
    with pytest.raises(ProviderError) as caught:
        await http.request("GET", "https://chatgpt.com/x", headers={}, allow_local=True, total_timeout_s=2)
    assert caught.value.reason == "host_not_allowed"
    for url in ("https://auth.openai.com/x", "https://chatgpt.com/backend-api/codex/models"):
        with pytest.raises(ProviderError) as caught:  # allowed: it gets as far as resolving the name
            await http.request("GET", url, headers={}, allow_local=False, total_timeout_s=2)
        assert caught.value.reason == "name_not_resolved"
