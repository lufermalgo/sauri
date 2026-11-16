"""Base URL policy: shape, HTTPS, loopback and SSRF rejections."""

from __future__ import annotations

import pytest

from app.engines import urls
from app.engines.urls import BaseUrlError, origin_of, validate_base_url


async def _code(url: str, *, allow_loopback: bool = False) -> str | None:
    try:
        await validate_base_url(url, allow_loopback=allow_loopback)
    except BaseUrlError as exc:
        return exc.code
    return None


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1",
        "https://api.openai.com/v1/",
        "https://example.org:8443/openai/v1",
        "https://8.8.8.8/v1",
        "https://[2606:4700:4700::1111]/v1",
    ],
)
async def test_public_https_urls_are_accepted(url: str) -> None:
    assert await _code(url) is None


@pytest.mark.parametrize(
    "url",
    [
        "",
        "ftp://example.org",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "//example.org",
        "https://user@example.org",
        "https://user:pass@example.org",
        "https://example.org/v1#frag",
        "https://example.org/v1?key=1",
        "https://example.org/v1?",
        "https://exam ple.org",
        "https://example.org\\@evil.test",
        "https://example.org:0/v1",
        "https://example.org:99999/v1",
        "https:///path",
        "https://example.org/\x00",
        "https://" + "a" * 3000 + ".org",
    ],
)
async def test_malformed_urls_are_rejected(url: str) -> None:
    assert await _code(url, allow_loopback=True) == "invalid_base_url"


async def test_plain_http_is_only_for_loopback() -> None:
    assert await _code("http://example.org/v1") == "https_required"
    assert await _code("http://127.0.0.1:11434/v1", allow_loopback=True) is None
    assert await _code("http://localhost:1234/v1", allow_loopback=True) is None
    assert await _code("http://[::1]:1234/v1", allow_loopback=True) is None
    assert await _code("https://127.0.0.1:8443/v1", allow_loopback=True) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://169.254.169.254/latest/meta-data",
        "https://[fd00:ec2::254]/",
        "https://[fe80::1]/",
        "https://[::ffff:169.254.169.254]/",
        "https://[::ffff:10.0.0.1]/",
        "https://10.0.0.5/v1",
        "https://172.16.0.1/v1",
        "https://192.168.1.10/v1",
        "https://100.64.0.1/v1",
        "https://0.0.0.0/",
        "https://224.0.0.1/",
        "https://[fc00::1]/",
        "https://metadata.google.internal/",
        "https://metadata/",
        "https://intranet/",
        "https://printer.local/",
        "https://db.corp/",
        "https://2130706433/",
        "https://0x7f.1/",
        "https://017700000001/",
    ],
)
async def test_internal_targets_are_rejected_even_over_https(url: str) -> None:
    assert await _code(url, allow_loopback=True) == "base_url_not_allowed"


async def test_loopback_needs_a_local_kind_and_avoids_sauri_ports() -> None:
    assert await _code("http://127.0.0.1:11434/v1", allow_loopback=False) == "base_url_not_allowed"
    for port in (8000, 8001, 8002, 8003, 8004, 8005, 5432):
        assert await _code(f"http://127.0.0.1:{port}/v1", allow_loopback=True) == "base_url_not_allowed"
    assert await _code("http://localhost:8005", allow_loopback=True) == "base_url_not_allowed"


async def test_hostnames_resolving_to_internal_addresses_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    async def internal(host: str) -> list[str]:
        return ["93.184.216.34", "127.0.0.1"]

    monkeypatch.setattr(urls, "resolve_host", internal)
    assert await _code("https://rebind.example.org/v1") == "base_url_not_allowed"

    async def metadata(host: str) -> list[str]:
        return ["169.254.169.254"]

    monkeypatch.setattr(urls, "resolve_host", metadata)
    assert await _code("https://rebind.example.org/v1") == "base_url_not_allowed"


async def test_unresolvable_names_are_left_to_the_connection_time_check(monkeypatch: pytest.MonkeyPatch) -> None:
    async def nothing(host: str) -> list[str]:
        return []

    monkeypatch.setattr(urls, "resolve_host", nothing)
    assert await _code("https://offline.example.org/v1") is None


def test_origin_matches_the_gateway_contract() -> None:
    from sauri_engine_common.route import origin_of as gateway_origin

    for url in (
        "https://api.openai.com/v1",
        "https://API.OpenAI.com:443/v1",
        "http://127.0.0.1:11434/v1",
        "http://localhost:80",
        "https://[::1]:8443/x",
        "https://example.org:8443",
    ):
        assert origin_of(url) == gateway_origin(url)
