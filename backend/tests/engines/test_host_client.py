"""The host client: token handling, error mapping and reference validation, against a fake host."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from app.engines.host_client import HostClient, HostError, HostRejectedError, HostUnavailableError, valid_secret_ref
from tests.engines.conftest import MANAGEMENT_TOKEN, FakeHost, build_fake_host


@pytest.fixture
def token_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "management_token"
    path.write_text(MANAGEMENT_TOKEN + "\n")
    monkeypatch.setenv("MANAGEMENT_TOKEN_FILE", str(path))
    return path


def _client(state: FakeHost) -> HostClient:
    return HostClient("http://host.test", transport=ASGITransport(app=build_fake_host(state)))


async def test_put_and_delete_secret_round_trip(token_file: Path) -> None:
    state = FakeHost()
    client = _client(state)
    assert await client.put_secret("sauri/o/p", "k" * 20, "https://api.example.com") == "kkkk"
    assert state.secrets["sauri/o/p"] == {"key": "k" * 20, "origin": "https://api.example.com"}
    await client.delete_secret("sauri/o/p")
    assert state.secrets == {}


async def test_short_keys_have_no_hint(token_file: Path) -> None:
    assert await _client(FakeHost()).put_secret("sauri/o/p", "short", "https://api.example.com") is None


async def test_missing_token_file_is_unavailable_and_nothing_is_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MANAGEMENT_TOKEN_FILE", str(tmp_path / "absent"))
    state = FakeHost()
    with pytest.raises(HostUnavailableError):
        await _client(state).engines_status()
    assert state.calls == []


async def test_wrong_token_and_host_down_are_unavailable(token_file: Path) -> None:
    token_file.write_text("another-token\n")
    with pytest.raises(HostUnavailableError):
        await _client(FakeHost()).engines_status()
    token_file.write_text(MANAGEMENT_TOKEN)
    with pytest.raises(HostUnavailableError):
        await _client(FakeHost(down=True)).engines_status()


async def test_connection_failure_is_unavailable_without_logging_the_url_or_token(
    token_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class Refusing(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused http://secret-host.test token", request=request)

    caplog.set_level(logging.DEBUG)
    with pytest.raises(HostUnavailableError):
        await HostClient("http://host.test", transport=Refusing()).engines_status()
    assert MANAGEMENT_TOKEN not in caplog.text
    assert "secret-host" not in caplog.text


async def test_rejections_carry_status_and_a_code_only(token_file: Path) -> None:
    state = FakeHost(secret_status=422)
    with pytest.raises(HostRejectedError) as raised:
        await _client(state).put_secret("sauri/o/p", "k" * 20, "https://api.example.com")
    assert raised.value.status == 422
    assert raised.value.code == "secret_unavailable"


async def test_unconfigured_or_invalid_url_is_unavailable(token_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOST_ENGINE_URL", raising=False)
    with pytest.raises(HostUnavailableError):
        await HostClient().engines_status()
    with pytest.raises(HostUnavailableError):
        await HostClient("ftp://host.test").engines_status()
    with pytest.raises(HostUnavailableError):
        await HostClient("http://user:pw@host.test").engines_status()


async def test_url_comes_from_the_environment(token_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOST_ENGINE_URL", "http://host.test/")
    state = FakeHost()
    client = HostClient(transport=ASGITransport(app=build_fake_host(state)))
    assert (await client.engines_status())["secret_store"] == "file"
    assert state.calls[-1][:2] == ("GET", "/v1/engines/status")


@pytest.mark.parametrize(
    "ref",
    [
        "",
        "..",
        "../x",
        "sauri/../x",
        "sauri//x",
        "/sauri/o",
        "sauri/o/",
        "sauri/./o",
        "a b",
        "a?b",
        "a#b",
        "a%2fb",
        "x" * 201,
    ],
)
async def test_references_that_could_escape_the_secret_route_are_refused(ref: str, token_file: Path) -> None:
    state = FakeHost()
    assert not valid_secret_ref(ref)
    with pytest.raises(HostError):
        await _client(state).put_secret(ref, "k" * 20, "https://api.example.com")
    with pytest.raises(HostError):
        await _client(state).delete_secret(ref)
    assert state.calls == []


def test_regular_references_are_valid() -> None:
    assert valid_secret_ref("sauri/00000000-0000-4000-8000-00000000000a/00000000-0000-4000-8000-00000000000b")
    assert valid_secret_ref("sauri/dev-user-00000000/p.1")


async def test_oversized_answer_is_unavailable(token_file: Path) -> None:
    state = FakeHost(status_answer={"engines": [], "padding": "x" * (1024 * 1024 + 10)})
    with pytest.raises(HostUnavailableError):
        await _client(state).engines_status()
