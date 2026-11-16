"""Route contract: round trip, strict decoding, and the validation order of ``validate_route``."""

from __future__ import annotations

import base64
import contextlib
import json
from dataclasses import replace
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sauri_engine_common.external.errors import ProviderError
from sauri_engine_common.route import (
    CAPABILITIES,
    MAX_HEADER_BYTES,
    TRANSPORTS,
    Route,
    RouteError,
    RouteTimeouts,
    decode_route,
    encode_route,
    is_loopback_host,
    origin_of,
    validate_route,
)
from sauri_engine_common.secrets import SecretRecord

ORIGIN = "https://api.example.com"


class DictMatrix:
    """Test double for the API-owned capability matrix."""

    def __init__(self, allowed: set[tuple[str, str, str]]) -> None:
        self.allowed = allowed

    def supports(self, kind: str, capability: str, transport: str) -> bool:
        return (kind, capability, transport) in self.allowed


MATRIX = DictMatrix({("openai", "summary", "openai-chat"), ("assemblyai", "transcription", "assemblyai")})


def external(**changes: Any) -> Route:
    route = Route(
        version=1,
        capability="summary",
        kind="openai",
        transport="openai-chat",
        base_url=f"{ORIGIN}/v1",
        model="gpt-x",
        secret_ref="sauri/owner/provider",
        consent_version=1,
        timeouts=RouteTimeouts(),
    )
    return replace(route, **changes)


def local() -> Route:
    return Route(
        version=1, capability="summary", kind="local", transport=None, base_url=None,
        model="local:qwen3.5-9b", secret_ref=None, consent_version=None,
    )


def raw_header(data: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


def good_payload() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(base64.urlsafe_b64decode(encode_route(external()) + "=="))
    return payload


# --- encode / decode --------------------------------------------------------------------------------

timeouts = st.builds(
    RouteTimeouts,
    connect_s=st.floats(0.1, 1000), first_byte_s=st.floats(0.1, 1000),
    idle_s=st.floats(0.1, 1000), total_s=st.floats(0.1, 80000),
)
routes = st.builds(
    Route,
    version=st.just(1),
    capability=st.sampled_from(sorted(CAPABILITIES)),
    kind=st.text(alphabet="abcdefghij-_0123456789", min_size=1, max_size=30),
    transport=st.one_of(st.none(), st.sampled_from(sorted(TRANSPORTS))),
    base_url=st.one_of(st.none(), st.just("https://api.example.com/v1")),
    model=st.text(min_size=1, max_size=60),
    secret_ref=st.one_of(st.none(), st.from_regex(r"[A-Za-z0-9._/-]{1,100}", fullmatch=True)),
    consent_version=st.one_of(st.none(), st.integers(1, 50)),
    timeouts=timeouts,
)


@given(routes)
def test_encode_decode_round_trip(route: Route) -> None:
    header = encode_route(route)
    assert len(header) <= MAX_HEADER_BYTES and "=" not in header
    assert decode_route(header) == route


def test_no_header_means_the_local_engine() -> None:
    assert decode_route(None) is None


def test_the_header_carries_no_key_or_content_fields() -> None:
    payload = json.dumps(good_payload())
    assert "key" not in good_payload() and "authorization" not in payload.lower()


def test_oversized_routes_are_refused_on_both_sides() -> None:
    with pytest.raises(RouteError) as encoded:
        encode_route(external(model="m" * 5000))
    assert encoded.value.reason == "route_too_large"
    with pytest.raises(RouteError) as decoded:
        decode_route("A" * (MAX_HEADER_BYTES + 1))
    assert decoded.value.reason == "route_too_large" and decoded.value.code == "provider_bad_request"


def test_a_header_at_the_limit_is_decoded_not_rejected_for_size() -> None:
    with pytest.raises(RouteError) as caught:
        decode_route("A" * MAX_HEADER_BYTES)
    assert caught.value.reason == "route_malformed"


@pytest.mark.parametrize("version", [0, 2, 99, -1])
def test_unknown_versions_are_rejected(version: int) -> None:
    with pytest.raises(RouteError) as caught:
        decode_route(raw_header({**good_payload(), "version": version}))
    assert caught.value.reason == "route_version_unknown"


@pytest.mark.parametrize("capability", ["video", "", "Summary", "transcribe"])
def test_unsupported_processes_are_rejected(capability: str) -> None:
    with pytest.raises(RouteError) as caught:
        decode_route(raw_header({**good_payload(), "capability": capability}))
    assert caught.value.reason == "route_capability_unsupported"


@pytest.mark.parametrize(
    "mutation",
    [
        {"version": True}, {"version": "1"}, {"kind": ""}, {"kind": 5}, {"model": ""}, {"model": None},
        {"transport": "carrier-pigeon"}, {"transport": 3}, {"base_url": ""}, {"base_url": "x" * 3000},
        {"secret_ref": "bad ref"}, {"secret_ref": 7}, {"consent_version": 0}, {"consent_version": True},
        {"consent_version": "1"}, {"unexpected": 1}, {"timeouts": []}, {"timeouts": {"nope": 1}},
        {"timeouts": {"total_s": 0}}, {"timeouts": {"total_s": -3}}, {"timeouts": {"total_s": True}},
        {"timeouts": {"total_s": "9"}}, {"timeouts": {"total_s": 10**9}},
    ],
)
def test_malformed_fields_are_rejected(mutation: dict[str, Any]) -> None:
    with pytest.raises(RouteError) as caught:
        decode_route(raw_header({**good_payload(), **mutation}))
    assert caught.value.code == "provider_bad_request"


@pytest.mark.parametrize("header", ["", "!!!", "e30", raw_header([]), raw_header("x"), "bm90LWpzb24"])
def test_garbage_headers_are_rejected(header: str) -> None:
    with pytest.raises(RouteError):
        decode_route(header)


def test_nan_and_infinite_timeouts_are_rejected() -> None:
    payload = good_payload()
    for bad in ("NaN", "Infinity"):
        text = json.dumps({**payload, "timeouts": {"total_s": 1}}).replace('"total_s": 1', f'"total_s": {bad}')
        header = base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")
        with pytest.raises(RouteError):
            decode_route(header)


@given(st.text(max_size=300))
def test_decode_never_raises_anything_but_route_error(header: str) -> None:
    with contextlib.suppress(RouteError):
        decode_route(header)


# --- origins ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "origin"),
    [
        ("https://API.Example.com/v1/x?y=1", "https://api.example.com"),
        ("https://api.example.com:443/", "https://api.example.com"),
        ("http://127.0.0.1:11434/v1", "http://127.0.0.1:11434"),
        ("http://[::1]:1234/v1", "http://[::1]:1234"),
        ("https://api.example.com:8443", "https://api.example.com:8443"),
    ],
)
def test_origin_of_is_canonical(url: str, origin: str) -> None:
    assert origin_of(url) == origin


@pytest.mark.parametrize(
    "url",
    ["", "ftp://x.example.com", "https://", "https://u:p@x.example.com", "https://x.example.com:99999", "//x.com"],
)
def test_origin_of_rejects_non_http_and_credentials(url: str) -> None:
    with pytest.raises(RouteError):
        origin_of(url)


@pytest.mark.parametrize("host", ["127.0.0.1", "127.9.9.9", "::1", "localhost", "LOCALHOST"])
def test_loopback_hosts(host: str) -> None:
    assert is_loopback_host(host)


@pytest.mark.parametrize("host", ["10.0.0.1", "192.168.1.5", "example.com", "localhost.evil.com", "0.0.0.0", ""])
def test_non_loopback_hosts(host: str) -> None:
    assert not is_loopback_host(host)


# --- validate_route ---------------------------------------------------------------------------------


def secret(origin: str = ORIGIN) -> SecretRecord:
    return SecretRecord(key="k" * 20, origin=origin)


def code_of(route: Route, record: SecretRecord | None) -> str:
    with pytest.raises(ProviderError) as caught:
        validate_route(route, MATRIX, record)
    return caught.value.code


def test_a_valid_external_route_passes() -> None:
    validate_route(external(), MATRIX, secret())
    validate_route(external(base_url="https://API.example.com:443/other/path"), MATRIX, secret())


def test_local_routes_need_nothing() -> None:
    validate_route(local(), MATRIX, None)
    with pytest.raises(RouteError):
        validate_route(replace(local(), base_url="https://evil.example.com"), MATRIX, None)


@given(
    st.sampled_from(["openai", "assemblyai", "anthropic", "x"]),
    st.sampled_from(sorted(CAPABILITIES)),
    st.sampled_from(sorted(TRANSPORTS) + [None]),
)
def test_pairs_outside_the_matrix_are_unsupported(kind: str, capability: str, transport: str | None) -> None:
    """Property 6, gateway side: no contact with the provider; validation fails first."""
    route = external(kind=kind, capability=capability, transport=transport)
    if transport is not None and (kind, capability, transport) in MATRIX.allowed:
        return
    assert code_of(route, secret()) == "provider_unsupported"


def test_consent_is_required_for_every_external_route() -> None:
    assert code_of(external(consent_version=None), secret()) == "consent_missing"


def test_matrix_support_is_checked_before_consent() -> None:
    assert code_of(external(kind="other", consent_version=None), secret()) == "provider_unsupported"


@given(st.sampled_from(["example.com", "api.example.com", "10.0.0.5", "192.168.1.9", "8.8.8.8", "localhost.evil.com"]))
def test_plain_http_is_refused_outside_loopback(host: str) -> None:
    """Property 5: no non-loopback http URL is ever accepted."""
    with pytest.raises(ProviderError) as caught:
        validate_route(external(base_url=f"http://{host}/v1"), MATRIX, secret(f"http://{host}"))
    assert caught.value.reason == "https_required"


@pytest.mark.parametrize("base", ["http://127.0.0.1:11434/v1", "http://localhost:1234/v1", "http://[::1]:8080"])
def test_plain_http_is_allowed_on_loopback(base: str) -> None:
    validate_route(external(base_url=base), MATRIX, secret(origin_of(base)))


@pytest.mark.parametrize(
    "base", [None, "", "ftp://api.example.com", "https://u:p@api.example.com", "https://api.example.com/v1?x=1",
             "https://api.example.com/#f", "not a url"]
)
def test_unusable_base_urls_are_refused(base: str | None) -> None:
    with pytest.raises(ProviderError) as caught:
        validate_route(external(base_url=base), MATRIX, secret())
    assert caught.value.code == "provider_bad_request"


@given(st.sampled_from(["https://other.example.com", "https://api.example.com:8443", "http://api.example.com",
                        "https://api.example.com.evil.com", "https://evilapi.example.com"]))
def test_origin_mismatch_blocks_the_route(bound_origin: str) -> None:
    """Property 5: a key issued for one origin is never usable for another."""
    assert code_of(external(), secret(bound_origin)) == "origin_mismatch"


def test_a_garbled_bound_origin_is_a_mismatch() -> None:
    assert code_of(external(), secret("not an origin")) == "origin_mismatch"


def test_missing_secret_is_unavailable_but_keyless_providers_pass() -> None:
    assert code_of(external(), None) == "secret_unavailable"
    validate_route(external(secret_ref=None), MATRIX, None)


def test_errors_carry_codes_never_values() -> None:
    record = SecretRecord(key="TOPSECRET-VALUE-123", origin="https://other.example.com")
    with pytest.raises(ProviderError) as caught:
        validate_route(external(), MATRIX, record)
    assert "TOPSECRET" not in str(caught.value) + repr(caught.value) + str(caught.value.to_payload())
