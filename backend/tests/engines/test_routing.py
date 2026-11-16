"""Route resolution and the local fallback (design properties 1, 2, 14, 15), on SQLite and PostgreSQL."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Callable
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sauri_engine_common.external.errors import ERROR_CODES, RETRYABLE, ProviderError
from sauri_engine_common.route import Route
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.copy.engine_notices_es import NOTICE_VERSIONS
from app.engines.routing import EXTERNAL_TOTAL_S, Provenance, ResolvedRoute, call_with_fallback, resolve_route
from tests.engines.conftest import OTHER, OWNER
from tests.external_asr_support import add_provider, choose, consent

Factory = async_sessionmaker[AsyncSession]


@pytest.fixture(autouse=True)
def only_loopback_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    """Property 1: resolving a route never reaches a non-loopback address."""
    original = socket.socket.connect

    def connect(self: socket.socket, address: Any) -> None:
        host = address[0] if isinstance(address, tuple) else address
        assert not isinstance(host, str) or host in {"127.0.0.1", "::1", "localhost"} or host.startswith("/")
        original(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)


async def resolve(factory: Factory, owner: str = OWNER, capability: str = "transcription") -> ResolvedRoute:
    async with factory() as session:
        return await resolve_route(session, owner, capability)  # type: ignore[arg-type]


async def test_property_1_no_setting_means_the_local_engine_and_no_remote_connection(engines_db: Factory) -> None:
    assert await resolve(engines_db) == ResolvedRoute(None, False, None)
    await add_provider(engines_db)
    await choose(engines_db, None, "local:default")
    assert await resolve(engines_db) == ResolvedRoute(None)  # a provider without a choice is never used


async def test_a_local_model_choice_travels_as_a_local_route(engines_db: Factory) -> None:
    await choose(engines_db, None, "local:whisper-small")
    resolved = await resolve(engines_db)
    assert resolved.route is not None
    assert (resolved.route.kind, resolved.route.model) == ("local", "local:whisper-small")
    assert resolved.route.transport is None and resolved.route.secret_ref is None and not resolved.local_fallback


async def test_property_2_external_route_needs_the_exact_current_consent(engines_db: Factory) -> None:
    a, b = await add_provider(engines_db), await add_provider(engines_db, kind="deepgram", base_url="https://api.deepgram.com")
    other_owner = await add_provider(engines_db, owner=OTHER)
    await choose(engines_db, a)
    for stray in (
        {"provider_id": b},  # another provider, same owner and process
        {"provider_id": a, "capability": "diarization"},  # same provider, another process
        {"provider_id": other_owner, "owner": OTHER},  # another owner
        {"provider_id": a, "revoked": True},  # revoked
    ):
        await consent(engines_db, **stray)
        with pytest.raises(ProviderError) as refused:
            await resolve(engines_db)
        assert refused.value.code == "consent_missing" and not refused.value.retryable
    await consent(engines_db, a)
    resolved = await resolve(engines_db)
    assert resolved.route is not None
    assert (resolved.route.kind, resolved.route.transport) == ("assemblyai", "assemblyai")
    assert resolved.route.consent_version == NOTICE_VERSIONS["transcription"]


async def test_property_2_an_older_notice_version_no_longer_counts(
    engines_db: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = await add_provider(engines_db)
    await choose(engines_db, provider)
    await consent(engines_db, provider)
    assert (await resolve(engines_db)).route is not None
    monkeypatch.setitem(NOTICE_VERSIONS, "transcription", NOTICE_VERSIONS["transcription"] + 1)
    with pytest.raises(ProviderError) as refused:
        await resolve(engines_db)
    assert refused.value.code == "consent_missing"


async def test_the_route_carries_references_never_keys_and_a_bounded_attempt(engines_db: Factory) -> None:
    provider = await add_provider(engines_db, kind="groq", base_url="https://api.groq.com/openai/v1")
    await choose(engines_db, provider, "whisper-large-v3-turbo", fallback=False)
    await consent(engines_db, provider)
    resolved = await resolve(engines_db)
    route = resolved.route
    assert route is not None and not resolved.local_fallback
    assert (route.kind, route.transport, route.model) == ("groq", "openai-audio", "whisper-large-v3-turbo")
    assert route.secret_ref == "sauri/owner/provider" and route.base_url == "https://api.groq.com/openai/v1"
    assert route.timeouts.total_s == EXTERNAL_TOTAL_S


async def test_disabled_provider_and_unsupported_pair(engines_db: Factory) -> None:
    disabled = await add_provider(engines_db, enabled=False)
    await choose(engines_db, disabled)
    await consent(engines_db, disabled)
    assert (await resolve(engines_db)).route is None  # back to local, nothing leaves
    unsupported = await add_provider(engines_db, kind="openai", base_url="https://api.openai.com/v1")
    await choose(engines_db, unsupported)
    with pytest.raises(ProviderError) as refused:
        await resolve(engines_db)
    assert refused.value.code == "provider_unsupported"


async def test_property_15_a_change_applies_to_the_next_attempt_without_restarting(engines_db: Factory) -> None:
    provider = await add_provider(engines_db)
    await consent(engines_db, provider)
    assert (await resolve(engines_db)).route is None
    await choose(engines_db, provider)
    assert (await resolve(engines_db)).route is not None
    await choose(engines_db, None, "local:default")
    assert (await resolve(engines_db)).route is None


# --- call_with_fallback --------------------------------------------------------------------------------

EXTERNAL = Route(
    version=1, capability="transcription", kind="assemblyai", transport="assemblyai", base_url="https://x.example",
    model="m", secret_ref="sauri/a/b", consent_version=1,
)
LOCAL = Route(version=1, capability="transcription", kind="local", transport=None, base_url=None, model="local:x",
              secret_ref=None, consent_version=None)


def identify(result: tuple[str, str]) -> tuple[str, str]:
    return result


class Calls:
    def __init__(self, outcomes: dict[str | None, Callable[[], tuple[str, str]]]) -> None:
        self.outcomes = outcomes
        self.routes: list[Route | None] = []

    async def __call__(self, route: Route | None) -> tuple[str, str]:
        self.routes.append(route)
        return self.outcomes["external" if route is not None and route.kind != "local" else "local"]()


def failing(code: str) -> Callable[[], tuple[str, str]]:
    def raise_it() -> tuple[str, str]:
        raise ProviderError(code)

    return raise_it


async def test_success_records_the_engine_that_answered() -> None:
    calls = Calls({"external": lambda: ("assemblyai", "universal-2"), "local": lambda: ("whisper.cpp", "m")})
    value, provenance = await call_with_fallback(ResolvedRoute(EXTERNAL, True), calls, identify)
    assert value == ("assemblyai", "universal-2") and provenance == Provenance("assemblyai", "universal-2", True)
    assert calls.routes == [EXTERNAL]


async def test_transient_failure_with_fallback_uses_the_local_engine_and_records_the_real_one() -> None:
    calls = Calls({"external": failing("provider_unavailable"), "local": lambda: ("whisper.cpp", "ggml-large")})
    value, provenance = await call_with_fallback(ResolvedRoute(EXTERNAL, True, LOCAL), calls, identify)
    assert value == ("whisper.cpp", "ggml-large")
    assert provenance == Provenance("whisper.cpp", "ggml-large", False, "provider_unavailable")
    assert calls.routes == [EXTERNAL, LOCAL]


async def test_default_local_fallback_sends_no_route() -> None:
    calls = Calls({"external": failing("provider_timeout"), "local": lambda: ("whisper.cpp", "m")})
    await call_with_fallback(ResolvedRoute(EXTERNAL, True), calls, identify)
    assert calls.routes == [EXTERNAL, None]


async def test_without_fallback_the_failure_surfaces() -> None:
    calls = Calls({"external": failing("provider_unavailable"), "local": lambda: ("never", "called")})
    with pytest.raises(ProviderError):
        await call_with_fallback(ResolvedRoute(EXTERNAL, False), calls, identify)
    assert calls.routes == [EXTERNAL]


async def test_a_failing_fallback_is_not_retried_or_chained() -> None:
    calls = Calls({"external": failing("provider_unavailable"), "local": failing("provider_unavailable")})
    with pytest.raises(ProviderError):
        await call_with_fallback(ResolvedRoute(EXTERNAL, True), calls, identify)
    assert calls.routes == [EXTERNAL, None]


async def test_local_routes_never_fall_back() -> None:
    calls = Calls({"external": failing("provider_unavailable"), "local": failing("provider_unavailable")})
    with pytest.raises(ProviderError):
        await call_with_fallback(ResolvedRoute(None, True), calls, identify)
    assert calls.routes == [None]


def test_the_fallback_route_must_be_local() -> None:
    with pytest.raises(ValueError, match="local"):
        ResolvedRoute(EXTERNAL, True, EXTERNAL)


@given(code=st.sampled_from(sorted(ERROR_CODES)), fallback=st.booleans(), has_local_route=st.booleans())
def test_property_14_the_fallback_never_escalates(code: str, fallback: bool, has_local_route: bool) -> None:
    asyncio.run(_property_14(code, fallback, has_local_route))


async def _property_14(code: str, fallback: bool, has_local_route: bool) -> None:
    calls = Calls({"external": failing(code), "local": lambda: ("whisper.cpp", "m")})
    resolved = ResolvedRoute(EXTERNAL, fallback, LOCAL if has_local_route else None)
    if RETRYABLE[code] and fallback:
        _value, provenance = await call_with_fallback(resolved, calls, identify)
        assert len(calls.routes) == 2 and calls.routes[0] == EXTERNAL
        second = calls.routes[1]
        assert second is None or second.kind == "local"  # never a provider, never the same external route
        assert not provenance.external and provenance.fallback_reason == code
    else:
        with pytest.raises(ProviderError) as raised:
            await call_with_fallback(resolved, calls, identify)
        assert raised.value.code == code and calls.routes == [EXTERNAL]


async def test_user_action_classes_do_not_change_engine() -> None:
    for code in ("provider_auth", "consent_missing", "origin_mismatch", "provider_bad_request",
                 "provider_invalid_output", "no_word_timestamps", "audio_too_large"):
        calls = Calls({"external": failing(code), "local": lambda: ("never", "called")})
        with pytest.raises(ProviderError):
            await call_with_fallback(ResolvedRoute(EXTERNAL, True), calls, identify)
        assert calls.routes == [EXTERNAL]
