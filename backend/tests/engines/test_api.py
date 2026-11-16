"""Engines API against a real database (SQLite and disposable PostgreSQL) and a fake host service.

Covers owner isolation (Property 17), consent exactness on the API side (Property 2), keys never
returned or logged (Property 3), closed compatibility (Property 6) and revert-to-local on disable or
delete (requirement 3.2). No real provider and no real host service are contacted.
"""

from __future__ import annotations

import json
import logging
import random
import string
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.copy.engine_notices_es import NOTICE_VERSIONS, PROCESS_NAMES
from app.infra.models import EnginePrivacyConsent, EngineProcessSetting, EngineProvider
from app.summaries.engine import probe_schema
from tests.engines.conftest import OTHER, OWNER, FakeHost, auth_headers

BASE = "/api/v1/engines"
KEY = "synthetic-provider-key-0123456789"


async def _create(
    api: AsyncClient, kind: str = "anthropic", label: str | None = None, user: str = OWNER, **extra: Any
) -> dict[str, Any]:
    response = await api.post(
        f"{BASE}/providers",
        json={"kind": kind, "label": label or f"{kind} account", **extra},
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


async def _with_key(api: AsyncClient, kind: str = "anthropic", user: str = OWNER, key: str = KEY) -> dict[str, Any]:
    provider = await _create(api, kind, user=user)
    response = await api.put(f"{BASE}/providers/{provider['id']}/key", json={"key": key}, headers=auth_headers(user))
    assert response.status_code == 200, response.text
    return provider


async def _choose(
    api: AsyncClient, capability: str, provider_id: str | None, model: str, user: str = OWNER, **extra: Any
) -> Response:
    return await api.put(
        f"{BASE}/processes/{capability}",
        json={"provider_id": provider_id, "model": model, "local_fallback": True, **extra},
        headers=auth_headers(user),
    )


async def _accepted(
    api: AsyncClient, capability: str, provider: dict[str, Any], model: str, user: str = OWNER
) -> Response:
    return await _choose(api, capability, provider["id"], model, user, notice_version=NOTICE_VERSIONS[capability])


# --- Authentication and the capability listing ----------------------------------------------------


async def test_every_route_requires_authentication(api: AsyncClient) -> None:
    for method, path in (
        ("GET", "/capabilities"),
        ("GET", "/providers"),
        ("POST", "/providers"),
        ("GET", "/providers/x"),
        ("PATCH", "/providers/x"),
        ("DELETE", "/providers/x"),
        ("PUT", "/providers/x/key"),
        ("DELETE", "/providers/x/key"),
        ("GET", "/providers/x/account"),
        ("POST", "/providers/x/account/start"),
        ("POST", "/providers/x/account/poll"),
        ("DELETE", "/providers/x/account"),
        ("POST", "/providers/x/test"),
        ("GET", "/providers/x/models?capability=summary"),
        ("GET", "/processes"),
        ("PUT", "/processes/summary"),
        ("GET", "/processes/summary/notice?provider_id=x"),
        ("GET", "/status"),
    ):
        response = await api.request(method, f"{BASE}{path}")
        assert response.status_code == 401, (method, path)


async def test_capabilities_lists_only_offered_pairs(api: AsyncClient) -> None:
    body = (await api.get(f"{BASE}/capabilities", headers=auth_headers())).json()
    assert body["notice_versions"] == {"transcription": 1, "diarization": 1, "summary": 1}
    kinds = {entry["kind"]: entry for entry in body["kinds"]}
    assert [entry["capability"] for entry in kinds["deepgram"]["capabilities"]] == ["transcription", "diarization"]
    assert [entry["capability"] for entry in kinds["anthropic"]["capabilities"]] == ["summary"]
    assert [entry["capability"] for entry in kinds["gemini"]["capabilities"]] == ["summary"]
    assert kinds["gemini"]["linkable"] is True
    assert kinds["chatgpt_plan"]["linkable"] is True and kinds["chatgpt_plan"]["auth"] == "account"
    assert kinds["chatgpt_plan"]["key_required"] is False and kinds["openai"]["auth"] == "key"
    assert [entry["capability"] for entry in kinds["chatgpt_plan"]["capabilities"]] == ["summary"]
    # Offered by the owner's decision, not verified live: the date is empty, never invented.
    assert kinds["chatgpt_plan"]["capabilities"][0]["verified_on"] is None
    assert kinds["ollama"]["key_required"] is False and kinds["openai"]["key_required"] is True
    for entry in kinds.values():
        for capability in entry["capabilities"]:
            assert capability["capability"] != "chat"
            assert capability["verified_on"] or entry["kind"] == "chatgpt_plan"


# --- Providers --------------------------------------------------------------------------------------


async def test_create_list_get_and_defaults(api: AsyncClient) -> None:
    created = await _create(api, "openai")
    assert created["base_url"] == "https://api.openai.com/v1"
    assert created["status"] == "no_key"
    assert (created["key_set"], created["key_hint"], created["used_by"]) == (False, None, [])
    assert "secret_ref" not in created and "owner_id" not in created
    assert (await api.get(f"{BASE}/providers/{created['id']}", headers=auth_headers())).json() == created
    assert [p["id"] for p in (await api.get(f"{BASE}/providers", headers=auth_headers())).json()] == [created["id"]]
    local = await _create(api, "ollama")
    assert local["status"] == "active" and local["base_url"] == "http://127.0.0.1:11434/v1"


async def test_creation_validates_kind_label_and_url(api: AsyncClient) -> None:
    headers = auth_headers()
    post = lambda body: api.post(f"{BASE}/providers", json=body, headers=headers)  # noqa: E731
    other = {"kind": "chatgpt_plan", "label": "x", "base_url": "https://api.example.com/v1"}
    assert (await post(other)).json() == {"detail": "base_url_fixed"}
    assert (await post({"kind": "openai_compatible", "label": "x"})).json() == {"detail": "base_url_required"}
    assert (await post({"kind": "nothing", "label": "x"})).status_code == 422
    assert (await post({"kind": "openai", "label": ""})).status_code == 422
    assert (await post({"kind": "openai", "label": "x" * 65})).status_code == 422
    assert (await post({"kind": "openai", "label": "bad\x07label"})).status_code == 422
    assert (await post({"kind": "openai", "label": "x", "owner_id": OTHER})).status_code == 422  # extra=forbid
    for url, code in (
        ("http://api.openai.com/v1", "https_required"),
        ("https://user:pw@api.openai.com/v1", "invalid_base_url"),
        ("https://api.openai.com/v1#x", "invalid_base_url"),
        ("ftp://api.openai.com", "invalid_base_url"),
        ("https://169.254.169.254/", "base_url_not_allowed"),
        ("https://10.1.2.3/v1", "base_url_not_allowed"),
        ("http://127.0.0.1:11434/v1", "base_url_not_allowed"),  # loopback only for local-server kinds
    ):
        response = await post({"kind": "openai", "label": "x", "base_url": url})
        assert (response.status_code, response.json()["detail"]) == (422, code), url
    for url in ("http://127.0.0.1:8005", "http://localhost:8003"):
        assert (await post({"kind": "ollama", "label": "x", "base_url": url})).json() == {
            "detail": "base_url_not_allowed"
        }
    assert (await post({"kind": "ollama", "label": "x", "base_url": "http://localhost:4000/v1"})).status_code == 201


async def test_validation_errors_never_echo_the_input(api: AsyncClient) -> None:
    response = await api.post(
        f"{BASE}/providers", json={"kind": "openai", "label": "x", "base_url": KEY * 100}, headers=auth_headers()
    )
    assert response.status_code == 422
    assert KEY not in response.text


async def test_label_is_unique_per_owner_and_providers_are_capped(api: AsyncClient) -> None:
    await _create(api, "openai", "Same")
    response = await api.post(f"{BASE}/providers", json={"kind": "anthropic", "label": "Same"}, headers=auth_headers())
    assert response.status_code == 409
    await _create(api, "anthropic", "Same", user=OTHER)  # another owner may reuse it
    for index in range(49):
        await _create(api, "openai", f"n{index}")
    response = await api.post(f"{BASE}/providers", json={"kind": "openai", "label": "one more"}, headers=auth_headers())
    assert response.status_code == 409


async def test_update_label_url_and_enabled(api: AsyncClient) -> None:
    provider = await _create(api, "openai_compatible", base_url="https://models.example.org/v1/")
    assert provider["base_url"] == "https://models.example.org/v1"
    response = await api.patch(
        f"{BASE}/providers/{provider['id']}",
        json={"label": "Renamed", "base_url": "https://other.example.org"},
        headers=auth_headers(),
    )
    body = response.json()
    assert (response.status_code, body["label"], body["base_url"], body["reverted_processes"]) == (
        200,
        "Renamed",
        "https://other.example.org",
        [],
    )
    other = await _create(api, "openai", "Taken")
    clash = await api.patch(f"{BASE}/providers/{other['id']}", json={"label": "Renamed"}, headers=auth_headers())
    assert clash.status_code == 409
    bad = await api.patch(
        f"{BASE}/providers/{provider['id']}", json={"base_url": "http://x.example.org"}, headers=auth_headers()
    )
    assert bad.json() == {"detail": "https_required"}
    assert (
        await api.patch(f"{BASE}/providers/{provider['id']}", json={"kind": "openai"}, headers=auth_headers())
    ).status_code == 422


async def test_key_bound_origin_cannot_change_without_replacing_the_key(api: AsyncClient, fake_host: FakeHost) -> None:
    provider = await _with_key(api, "openai")
    url = f"{BASE}/providers/{provider['id']}"
    moved = await api.patch(url, json={"base_url": "https://evil.example.org/v1"}, headers=auth_headers())
    assert (moved.status_code, moved.json()) == (409, {"detail": "key_bound_to_origin"})
    same_origin = await api.patch(url, json={"base_url": "https://api.openai.com/v2"}, headers=auth_headers())
    assert same_origin.status_code == 200
    await api.delete(f"{url}/key", headers=auth_headers())
    assert (
        await api.patch(url, json={"base_url": "https://evil.example.org/v1"}, headers=auth_headers())
    ).status_code == 200


# --- Owner isolation (Property 17) -----------------------------------------------------------------


async def test_other_owners_resources_are_not_found(api: AsyncClient, fake_host: FakeHost) -> None:
    mine = await _with_key(api, "anthropic")
    pid = mine["id"]
    assert await _accepted(api, "summary", mine, "claude-sonnet", user=OWNER)
    other = auth_headers(OTHER)
    for method, path, body in (
        ("GET", f"/providers/{pid}", None),
        ("PATCH", f"/providers/{pid}", {"label": "stolen"}),
        ("DELETE", f"/providers/{pid}", None),
        ("PUT", f"/providers/{pid}/key", {"key": KEY}),
        ("DELETE", f"/providers/{pid}/key", None),
        ("POST", f"/providers/{pid}/test", {}),
        ("GET", f"/providers/{pid}/models?capability=summary", None),
        ("GET", f"/processes/summary/notice?provider_id={pid}", None),
    ):
        response = await api.request(method, f"{BASE}{path}", json=body, headers=other)
        assert (response.status_code, response.json()) == (404, {"detail": "not_found"}), (method, path)
    denied = await _choose(api, "summary", pid, "claude-sonnet", OTHER, notice_version=1)
    assert (denied.status_code, denied.json()) == (404, {"detail": "not_found"})
    assert (await api.get(f"{BASE}/providers", headers=other)).json() == []
    assert all(p["provider_id"] is None for p in (await api.get(f"{BASE}/processes", headers=other)).json())
    # The owner's data is intact.
    assert (await api.get(f"{BASE}/providers/{pid}", headers=auth_headers())).json()["label"] != "stolen"
    assert fake_host.secrets  # nothing was deleted from the host
    assert len(fake_host.secrets) == 1


# --- Keys (Property 3) -----------------------------------------------------------------------------


async def test_key_goes_to_the_host_bound_to_the_provider_origin(api: AsyncClient, fake_host: FakeHost) -> None:
    provider = await _create(api, "openai")
    response = await api.put(f"{BASE}/providers/{provider['id']}/key", json={"key": KEY}, headers=auth_headers())
    assert response.status_code == 200
    assert response.json() == {"key_set": True, "key_hint": KEY[-4:], "reverted_processes": []}
    ref = f"sauri/{OWNER}/{provider['id']}"
    assert fake_host.secrets == {ref: {"key": KEY, "origin": "https://api.openai.com"}}
    shown = (await api.get(f"{BASE}/providers/{provider['id']}", headers=auth_headers())).json()
    assert (shown["key_set"], shown["key_hint"], shown["status"]) == (True, KEY[-4:], "active")
    assert KEY not in json.dumps(shown)


async def test_local_origin_keeps_its_port_and_short_keys_have_no_hint(api: AsyncClient, fake_host: FakeHost) -> None:
    provider = await _create(api, "ollama", base_url="http://localhost:4000/v1")
    response = await api.put(f"{BASE}/providers/{provider['id']}/key", json={"key": "short"}, headers=auth_headers())
    assert response.json()["key_hint"] is None
    assert next(iter(fake_host.secrets.values()))["origin"] == "http://localhost:4000"


async def test_replacing_a_key_refreshes_the_hint(api: AsyncClient) -> None:
    provider = await _with_key(api, "openai", key="first-key-0123456789-aaaa")
    response = await api.put(
        f"{BASE}/providers/{provider['id']}/key", json={"key": "second-key-0123456789-bbbb"}, headers=auth_headers()
    )
    assert response.json()["key_hint"] == "bbbb"


@pytest.mark.parametrize("key", ["", " ", "has space", "tab\there", "new\nline", "é" * 20, "x" * 2049])
async def test_unusable_keys_are_rejected_without_echo(api: AsyncClient, fake_host: FakeHost, key: str) -> None:
    provider = await _create(api, "openai")
    response = await api.put(f"{BASE}/providers/{provider['id']}/key", json={"key": key}, headers=auth_headers())
    assert response.status_code == 422
    assert key.strip() == "" or key not in response.text
    assert fake_host.secrets == {}
    assert (
        await api.put(
            f"{BASE}/providers/{provider['id']}/key",
            json={"key": KEY, "origin": "https://x.org"},
            headers=auth_headers(),
        )
    ).status_code == 422


async def test_random_keys_never_appear_in_any_response_log_or_row(
    api: AsyncClient,
    fake_host: FakeHost,
    engines_db: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    generator = random.Random(1087)
    alphabet = string.ascii_letters + string.digits + "-_.~+/="
    provider = await _create(api, "openai")
    seen: list[str] = []
    keys = ["".join(generator.choices(alphabet, k=generator.randint(12, 200))) for _ in range(25)]
    for key in keys:
        put = await api.put(f"{BASE}/providers/{provider['id']}/key", json={"key": key}, headers=auth_headers())
        seen.append(put.text)
        for path in (
            f"/providers/{provider['id']}",
            "/providers",
            "/processes",
            "/capabilities",
            "/status",
            f"/processes/summary/notice?provider_id={provider['id']}",
        ):
            seen.append((await api.get(f"{BASE}{path}", headers=auth_headers())).text)
        seen.append((await api.post(f"{BASE}/providers/{provider['id']}/test", json={}, headers=auth_headers())).text)
        seen.append(
            (await api.get(f"{BASE}/providers/{provider['id']}/models?capability=summary", headers=auth_headers())).text
        )
        hint = put.json()["key_hint"]
        assert hint == key[-4:]
        assert key not in " ".join(seen) and key not in caplog.text
    rows = []
    async with engines_db() as session:
        for table in ("engine_providers", "engine_process_settings", "engine_privacy_consents"):
            rows.append(str((await session.execute(text(f"SELECT * FROM {table}"))).all()))  # noqa: S608
    for key in keys:
        assert key not in " ".join(rows)
    # What the host was sent for probes and model lists never carries a key, only the reference.
    for _method, path, body in fake_host.calls:
        if path.startswith("/v1/providers/"):
            assert "key" not in body and body["secret_ref"] == f"sauri/{OWNER}/{provider['id']}"


async def test_provider_without_a_base_url_cannot_receive_a_key(
    api: AsyncClient, engines_db: async_sessionmaker[AsyncSession]
) -> None:
    provider = await _create(api, "openai")
    async with engines_db() as session, session.begin():
        row = await session.get(EngineProvider, provider["id"])
        assert row is not None
        row.base_url = None
    response = await api.put(f"{BASE}/providers/{provider['id']}/key", json={"key": KEY}, headers=auth_headers())
    assert response.json() == {"detail": "base_url_required"}


async def test_host_down_returns_503_and_stores_nothing(api: AsyncClient, fake_host: FakeHost) -> None:
    provider = await _create(api, "openai")
    fake_host.down = True
    response = await api.put(f"{BASE}/providers/{provider['id']}/key", json={"key": KEY}, headers=auth_headers())
    assert (response.status_code, response.json()) == (503, {"detail": "host_unavailable"})
    assert KEY not in response.text
    fake_host.down = False
    assert (await api.get(f"{BASE}/providers/{provider['id']}", headers=auth_headers())).json()["key_set"] is False
    fake_host.secret_status = 503  # the host answers but its store does not
    again = await api.put(f"{BASE}/providers/{provider['id']}/key", json={"key": KEY}, headers=auth_headers())
    assert again.json() == {"detail": "host_unavailable"}


async def test_delete_key_removes_it_from_the_host(api: AsyncClient, fake_host: FakeHost) -> None:
    provider = await _with_key(api, "ollama")
    response = await api.delete(f"{BASE}/providers/{provider['id']}/key", headers=auth_headers())
    assert response.json() == {"key_set": False, "key_hint": None, "reverted_processes": []}
    assert fake_host.secrets == {}
    again = await api.delete(f"{BASE}/providers/{provider['id']}/key", headers=auth_headers())
    assert again.json()["key_set"] is False


# --- Processes, consent and compatibility (Properties 2 and 6) -------------------------------------


async def test_everything_is_local_until_the_user_chooses(api: AsyncClient, fake_host: FakeHost) -> None:
    await _with_key(api, "anthropic")  # a linked provider alone changes nothing
    processes = (await api.get(f"{BASE}/processes", headers=auth_headers())).json()
    assert [p["capability"] for p in processes] == ["transcription", "diarization", "summary"]
    for process in processes:
        assert (process["provider_id"], process["configured"], process["model"], process["local_fallback"]) == (
            None,
            False,
            "local:default",
            True,
        )


async def test_choice_requires_the_current_notice_and_records_consent(
    api: AsyncClient, engines_db: async_sessionmaker[AsyncSession]
) -> None:
    provider = await _with_key(api, "anthropic")
    assert (await _choose(api, "summary", provider["id"], "claude-sonnet")).json() == {"detail": "notice_required"}
    assert (await _choose(api, "summary", provider["id"], "claude-sonnet", notice_version=2)).json() == {
        "detail": "notice_outdated"
    }
    response = await _accepted(api, "summary", provider, "claude-sonnet")
    body = response.json()
    assert response.status_code == 200
    assert (body["provider_id"], body["provider_kind"], body["model"], body["notice_version"], body["version"]) == (
        provider["id"],
        "anthropic",
        "claude-sonnet",
        1,
        1,
    )
    async with engines_db() as session:
        consents = (await session.execute(select(EnginePrivacyConsent))).scalars().all()
    assert [(c.owner_id, c.capability, c.provider_id, c.notice_version, c.revoked_at is None) for c in consents] == [
        (OWNER, "summary", provider["id"], 1, True)
    ]
    assert (await api.get(f"{BASE}/providers/{provider['id']}", headers=auth_headers())).json()["used_by"] == [
        "summary"
    ]


async def test_changing_the_model_within_the_same_provider_does_not_ask_again(
    api: AsyncClient, engines_db: async_sessionmaker[AsyncSession]
) -> None:
    provider = await _with_key(api, "anthropic")
    await _accepted(api, "summary", provider, "model-one")
    again = await _choose(api, "summary", provider["id"], "model-two")  # no notice_version
    assert (again.status_code, again.json()["model"], again.json()["version"]) == (200, "model-two", 2)
    async with engines_db() as session:
        consents = (await session.execute(select(EnginePrivacyConsent))).scalars().all()
    assert len(consents) == 1 and consents[0].revoked_at is None


async def test_consent_for_one_provider_never_covers_another_or_another_process(api: AsyncClient) -> None:
    first = await _with_key(api, "anthropic")
    second = await _create(api, "openai", "Second")
    await api.put(f"{BASE}/providers/{second['id']}/key", json={"key": KEY}, headers=auth_headers())
    await _accepted(api, "summary", first, "m")
    assert (await _choose(api, "summary", second["id"], "m")).json() == {"detail": "notice_required"}
    deepgram = await _with_key(api, "deepgram")
    await _accepted(api, "transcription", deepgram, "nova-3")
    assert (await _choose(api, "diarization", deepgram["id"], "nova-3")).json() == {"detail": "notice_required"}


async def test_switching_provider_revokes_the_previous_consent_and_going_local_revokes_all(
    api: AsyncClient, engines_db: async_sessionmaker[AsyncSession]
) -> None:
    first = await _with_key(api, "anthropic")
    second = await _create(api, "openai", "Second")
    await api.put(f"{BASE}/providers/{second['id']}/key", json={"key": KEY}, headers=auth_headers())
    await _accepted(api, "summary", first, "m")
    await _accepted(api, "summary", second, "m")
    async with engines_db() as session:
        by_provider = {c.provider_id: c for c in (await session.execute(select(EnginePrivacyConsent))).scalars()}
    assert by_provider[first["id"]].revoked_at is not None and by_provider[second["id"]].revoked_at is None
    local = await _choose(api, "summary", None, "local:default")
    assert (local.status_code, local.json()["provider_id"], local.json()["notice_version"]) == (200, None, None)
    async with engines_db() as session:
        assert all(c.revoked_at is not None for c in (await session.execute(select(EnginePrivacyConsent))).scalars())
    # Returning to the same provider asks again: the consent history is an audit trail, not a permission.
    assert (await _choose(api, "summary", second["id"], "m")).json() == {"detail": "notice_required"}
    assert (await _accepted(api, "summary", second, "m")).status_code == 200
    async with engines_db() as session:
        rows = (
            (
                await session.execute(
                    select(EnginePrivacyConsent).where(EnginePrivacyConsent.provider_id == second["id"])
                )
            )
            .scalars()
            .all()
        )
    assert sorted(r.revoked_at is None for r in rows) == [False, True]


async def test_an_outdated_consent_is_replaced_when_the_notice_is_accepted_again(
    api: AsyncClient, engines_db: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = await _with_key(api, "anthropic")
    await _accepted(api, "summary", provider, "m")
    monkeypatch.setitem(NOTICE_VERSIONS, "summary", 2)
    assert (await _choose(api, "summary", provider["id"], "m")).json() == {"detail": "notice_required"}
    shown = [
        p for p in (await api.get(f"{BASE}/processes", headers=auth_headers())).json() if p["capability"] == "summary"
    ][0]
    assert shown["notice_version"] == 1
    assert (await _choose(api, "summary", provider["id"], "m", notice_version=2)).status_code == 200
    async with engines_db() as session:
        versions = sorted(
            (c.notice_version, c.revoked_at is None)
            for c in (await session.execute(select(EnginePrivacyConsent))).scalars()
        )
    assert versions == [(1, False), (2, True)]


async def test_unsupported_unverified_and_reserved_pairs_are_422(api: AsyncClient, fake_host: FakeHost) -> None:
    anthropic = await _with_key(api, "anthropic")
    deepgram = await _with_key(api, "deepgram")
    gemini = await _with_key(api, "gemini")
    ollama = await _create(api, "ollama")
    for capability, provider in (
        ("transcription", anthropic),
        ("diarization", anthropic),
        ("summary", deepgram),
        ("transcription", gemini),  # Gemini serves summary only
        ("diarization", gemini),
        ("summary", ollama),  # not verified against its docs
    ):
        response = await _choose(api, capability, provider["id"], "m", notice_version=1)
        assert (response.status_code, response.json()) == (422, {"detail": "unsupported_provider"}), (
            capability,
            provider["kind"],
        )
    assert (await _choose(api, "chat", anthropic["id"], "m", notice_version=1)).status_code == 422
    assert (
        await api.get(f"{BASE}/processes/chat/notice?provider_id={anthropic['id']}", headers=auth_headers())
    ).status_code == 422
    assert all(p["provider_id"] is None for p in (await api.get(f"{BASE}/processes", headers=auth_headers())).json())


async def test_a_provider_must_be_enabled_and_have_its_key(api: AsyncClient) -> None:
    keyless = await _create(api, "anthropic")
    assert (await _choose(api, "summary", keyless["id"], "m", notice_version=1)).json() == {
        "detail": "provider_key_missing"
    }
    provider = await _with_key(api, "openai")
    await api.patch(f"{BASE}/providers/{provider['id']}", json={"enabled": False}, headers=auth_headers())
    assert (await _choose(api, "summary", provider["id"], "m", notice_version=1)).json() == {
        "detail": "provider_disabled"
    }


async def test_models_are_validated(api: AsyncClient) -> None:
    provider = await _with_key(api, "anthropic")
    for model in ("", "has space", "local:default", "bad\nmodel", "x" * 201, "-leading"):
        response = await _choose(api, "summary", provider["id"], model, notice_version=1)
        assert response.status_code == 422, repr(model)
    assert (await _choose(api, "summary", None, "claude-sonnet")).json() == {"detail": "invalid_model"}
    assert (await _choose(api, "summary", None, "local:whisper-large-v3-turbo-q5_0")).status_code == 200
    for model in ("anthropic/claude-3.5:free", "models/gemini-2.0-flash", "qwen2.5:7b-instruct"):
        assert (await _choose(api, "summary", provider["id"], model, notice_version=1)).status_code == 200


async def test_local_fallback_is_stored_and_defaults_on(api: AsyncClient) -> None:
    provider = await _with_key(api, "anthropic")
    response = await api.put(
        f"{BASE}/processes/summary",
        json={"provider_id": provider["id"], "model": "m", "notice_version": 1},
        headers=auth_headers(),
    )
    assert response.json()["local_fallback"] is True
    off = await _choose(api, "summary", provider["id"], "m")
    off = await api.put(
        f"{BASE}/processes/summary",
        json={"provider_id": provider["id"], "model": "m", "local_fallback": False},
        headers=auth_headers(),
    )
    assert off.json()["local_fallback"] is False


async def test_process_request_bodies_are_strict(api: AsyncClient) -> None:
    provider = await _with_key(api, "anthropic")
    for body in (
        {"provider_id": provider["id"], "model": "m", "unknown": 1},
        {"provider_id": provider["id"]},
        {"model": "m"},
        {"provider_id": "../x", "model": "m"},
        {"provider_id": provider["id"], "model": "m", "notice_version": 0},
        {"provider_id": provider["id"], "model": "m", "local_fallback": "yes"},
    ):
        assert (await api.put(f"{BASE}/processes/summary", json=body, headers=auth_headers())).status_code == 422, body


# --- Disable and delete send processes back to the local engine (requirement 3.2) -----------------


async def test_disabling_a_provider_returns_its_processes_to_local(
    api: AsyncClient, engines_db: async_sessionmaker[AsyncSession]
) -> None:
    deepgram = await _with_key(api, "deepgram")
    anthropic = await _with_key(api, "anthropic")
    await _accepted(api, "transcription", deepgram, "nova-3")
    await _accepted(api, "diarization", deepgram, "nova-3")
    await _accepted(api, "summary", anthropic, "m")
    response = await api.patch(f"{BASE}/providers/{deepgram['id']}", json={"enabled": False}, headers=auth_headers())
    body = response.json()
    assert (body["status"], body["reverted_processes"], body["used_by"]) == (
        "disabled",
        ["transcription", "diarization"],
        [],
    )
    processes = {p["capability"]: p for p in (await api.get(f"{BASE}/processes", headers=auth_headers())).json()}
    assert processes["transcription"]["provider_id"] is None and processes["transcription"]["model"] == "local:default"
    assert processes["summary"]["provider_id"] == anthropic["id"]  # untouched
    async with engines_db() as session:
        consents = {
            (c.capability, c.provider_id): c for c in (await session.execute(select(EnginePrivacyConsent))).scalars()
        }
    assert consents[("transcription", deepgram["id"])].revoked_at is not None
    assert consents[("summary", anthropic["id"])].revoked_at is None
    # Re-enabling does not bring the old choice back.
    await api.patch(f"{BASE}/providers/{deepgram['id']}", json={"enabled": True}, headers=auth_headers())
    assert (await api.get(f"{BASE}/providers/{deepgram['id']}", headers=auth_headers())).json()["used_by"] == []


async def test_deleting_a_provider_removes_its_key_and_leaves_processes_local(
    api: AsyncClient, fake_host: FakeHost, engines_db: async_sessionmaker[AsyncSession]
) -> None:
    provider = await _with_key(api, "anthropic")
    await _accepted(api, "summary", provider, "m")
    response = await api.delete(f"{BASE}/providers/{provider['id']}", headers=auth_headers())
    assert (response.status_code, response.json()) == (200, {"reverted_processes": ["summary"]})
    assert fake_host.secrets == {}
    assert (await api.get(f"{BASE}/providers/{provider['id']}", headers=auth_headers())).status_code == 404
    summary = [
        p for p in (await api.get(f"{BASE}/processes", headers=auth_headers())).json() if p["capability"] == "summary"
    ][0]
    assert (summary["provider_id"], summary["model"], summary["configured"]) == (None, "local:default", True)
    async with engines_db() as session:
        assert (await session.execute(select(EngineProcessSetting))).scalars().one().provider_id is None
        assert (await session.execute(select(EnginePrivacyConsent))).scalars().all() == []
    assert (await api.delete(f"{BASE}/providers/{provider['id']}", headers=auth_headers())).status_code == 404


async def test_deleting_a_provider_with_a_key_needs_the_host(api: AsyncClient, fake_host: FakeHost) -> None:
    provider = await _with_key(api, "anthropic")
    await _accepted(api, "summary", provider, "m")
    fake_host.down = True
    response = await api.delete(f"{BASE}/providers/{provider['id']}", headers=auth_headers())
    assert (response.status_code, response.json()) == (503, {"detail": "host_unavailable"})
    fake_host.down = False
    assert (await api.get(f"{BASE}/providers/{provider['id']}", headers=auth_headers())).json()["used_by"] == [
        "summary"
    ]
    keyless = await _create(api, "ollama")  # no key: no host call is needed
    fake_host.down = True
    assert (await api.delete(f"{BASE}/providers/{keyless['id']}", headers=auth_headers())).status_code == 200


async def test_removing_the_key_of_a_key_requiring_provider_returns_processes_to_local(
    api: AsyncClient, fake_host: FakeHost
) -> None:
    provider = await _with_key(api, "anthropic")
    await _accepted(api, "summary", provider, "m")
    response = await api.delete(f"{BASE}/providers/{provider['id']}/key", headers=auth_headers())
    assert response.json() == {"key_set": False, "key_hint": None, "reverted_processes": ["summary"]}
    assert (await api.get(f"{BASE}/providers/{provider['id']}", headers=auth_headers())).json()["status"] == "no_key"


async def test_keyless_local_server_keeps_its_process_when_no_key_exists(api: AsyncClient) -> None:
    provider = await _create(api, "openai_compatible", base_url="http://localhost:4000/v1")
    assert (await _accepted(api, "summary", provider, "any-model")).status_code == 200


# --- Notice, test, models and status -------------------------------------------------------------


async def test_notice_names_process_provider_address_and_billing(api: AsyncClient) -> None:
    provider = await _create(api, "deepgram")
    response = await api.get(
        f"{BASE}/processes/transcription/notice?provider_id={provider['id']}", headers=auth_headers()
    )
    body = response.json()
    text_ = " ".join([body["title"], *body["paragraphs"]])
    assert response.status_code == 200
    assert (body["notice_version"], body["address"], body["provider_name"]) == (
        1,
        "https://api.deepgram.com",
        "Deepgram",
    )
    assert PROCESS_NAMES["transcription"] in body["title"]
    assert "audio completo" in text_ and "se cobra en tu cuenta" in text_
    assert (
        await api.get(f"{BASE}/processes/summary/notice?provider_id={provider['id']}", headers=auth_headers())
    ).status_code == 422
    assert (await api.get(f"{BASE}/processes/summary/notice", headers=auth_headers())).status_code == 422
    ollama = await _create(api, "openai_compatible", base_url="http://localhost:4000/v1")
    local = (
        await api.get(f"{BASE}/processes/summary/notice?provider_id={ollama['id']}", headers=auth_headers())
    ).json()
    assert "este mismo equipo" in " ".join(local["paragraphs"]) and local["address"] == "http://localhost:4000"


async def test_the_notice_version_in_the_choice_matches_the_notice_served(api: AsyncClient) -> None:
    provider = await _with_key(api, "anthropic")
    notice = (
        await api.get(f"{BASE}/processes/summary/notice?provider_id={provider['id']}", headers=auth_headers())
    ).json()
    assert (
        await _choose(api, "summary", provider["id"], "m", notice_version=notice["notice_version"])
    ).status_code == 200


async def test_connection_test_sends_a_reference_not_a_key(api: AsyncClient, fake_host: FakeHost) -> None:
    provider = await _with_key(api, "anthropic")
    fake_host.probe_answer = {"ok": True, "latency_ms": 123, "json_schema_ok": True, "key": KEY, "extra": "x"}
    response = await api.post(
        f"{BASE}/providers/{provider['id']}/test", json={"capability": "summary"}, headers=auth_headers()
    )
    assert response.json() == {
        "ok": True, "latency_ms": 123, "error_class": None, "json_schema_ok": True,
        "schema_error_class": None, "schema_model": None,
    }  # fmt: skip
    method, path, body = [call for call in fake_host.calls if call[1] == "/v1/providers/probe"][-1]
    assert body.pop("response_schema") == probe_schema()  # the real summary shape, no key and no transcript
    assert body == {
        "kind": "anthropic",
        "transport": "anthropic-messages",
        "base_url": "https://api.anthropic.com",
        "secret_ref": f"sauri/{OWNER}/{provider['id']}",
        "capability": "summary",
    }
    assert (
        await api.post(f"{BASE}/providers/{provider['id']}/test", headers=auth_headers())
    ).status_code == 200  # no body
    assert (
        await api.post(
            f"{BASE}/providers/{provider['id']}/test", json={"capability": "transcription"}, headers=auth_headers()
        )
    ).status_code == 422


async def _last_probe(fake_host: FakeHost) -> dict[str, Any]:
    return [call for call in fake_host.calls if call[1] == "/v1/providers/probe"][-1][2]


async def test_connection_test_uses_the_model_chosen_for_the_summary(api: AsyncClient, fake_host: FakeHost) -> None:
    provider = await _with_key(api, "gemini")
    other = await _with_key(api, "anthropic")
    probe = f"{BASE}/providers/{provider['id']}/test"
    # Nothing chosen yet: no model is named, so the host falls back to the provider's starter model.
    await api.post(probe, json={"capability": "summary"}, headers=auth_headers())
    assert "model" not in await _last_probe(fake_host)
    # A model chosen on ANOTHER provider is not this provider's.
    assert (await _accepted(api, "summary", other, "claude-x")).status_code == 200
    await api.post(probe, json={"capability": "summary"}, headers=auth_headers())
    assert "model" not in await _last_probe(fake_host)
    # The owner's choice for this provider is the model under test, with the real (unadapted) summary schema.
    assert (await _accepted(api, "summary", provider, "gemini-3.1-flash-lite")).status_code == 200
    await api.post(probe, json={"capability": "summary"}, headers=auth_headers())
    body = await _last_probe(fake_host)
    assert body["model"] == "gemini-3.1-flash-lite" and body["capability"] == "summary"
    assert body["response_schema"] == probe_schema() and "P0000" in json.dumps(body["response_schema"])
    assert KEY not in json.dumps(body)
    # Another owner's choice never leaks in.
    stranger = await _with_key(api, "gemini", user=OTHER)
    await api.post(
        f"{BASE}/providers/{stranger['id']}/test", json={"capability": "summary"}, headers=auth_headers(OTHER)
    )
    assert "model" not in await _last_probe(fake_host)
    # A test without a capability stays the plain connection test: no schema, no model.
    await api.post(probe, json={}, headers=auth_headers())
    body = await _last_probe(fake_host)
    assert "response_schema" not in body and "model" not in body


@pytest.mark.parametrize(
    ("answer", "schema_ok", "schema_class"),
    [
        ({"json_schema_ok": True, "schema_model": "m1"}, True, None),
        ({"json_schema_ok": False, "schema_error_class": "provider_bad_request", "schema_model": "m1"}, False,
         "provider_bad_request"),  # incompatible
        ({"json_schema_ok": None, "schema_error_class": "provider_timeout", "schema_model": "m1"}, None,
         "provider_timeout"),  # slow
        ({"json_schema_ok": None, "schema_error_class": "provider_model_unavailable"}, None,
         "provider_model_unavailable"),
        ({"json_schema_ok": None, "schema_error_class": f"Bearer {KEY}"}, None, None),  # unknown values are dropped
    ],
    ids=["ok", "incompatible", "slow", "model-unavailable", "unknown-class"],
)
async def test_connection_test_tells_slow_from_incompatible(
    api: AsyncClient, fake_host: FakeHost, answer: dict[str, Any], schema_ok: bool | None, schema_class: str | None
) -> None:
    provider = await _with_key(api, "gemini")
    fake_host.probe_answer = {"ok": True, "latency_ms": 5, **answer}
    response = await api.post(
        f"{BASE}/providers/{provider['id']}/test", json={"capability": "summary"}, headers=auth_headers()
    )
    body = response.json()
    assert (body["ok"], body["json_schema_ok"], body["schema_error_class"]) == (True, schema_ok, schema_class)
    assert KEY not in json.dumps(body)


async def test_connection_test_classifies_failures_and_drops_unknown_values(
    api: AsyncClient, fake_host: FakeHost
) -> None:
    provider = await _with_key(api, "openai")
    fake_host.probe_answer = {"ok": False, "latency_ms": 9, "error_class": "provider_auth"}
    assert (await api.post(f"{BASE}/providers/{provider['id']}/test", json={}, headers=auth_headers())).json() == {
        "ok": False,
        "latency_ms": 9,
        "error_class": "provider_auth",
        "json_schema_ok": None,
        "schema_error_class": None,
        "schema_model": None,
    }
    fake_host.probe_answer = {"ok": False, "error_class": f"Bearer {KEY}", "latency_ms": -4}
    body = (await api.post(f"{BASE}/providers/{provider['id']}/test", json={}, headers=auth_headers())).json()
    assert body == {
        "ok": False, "latency_ms": None, "error_class": "provider_unavailable", "json_schema_ok": None,
        "schema_error_class": None, "schema_model": None,
    }  # fmt: skip
    fake_host.probe_status = 422
    fake_host.probe_answer = {"error": {"code": "provider_bad_request"}}
    assert (await api.post(f"{BASE}/providers/{provider['id']}/test", json={}, headers=auth_headers())).json()[
        "error_class"
    ] == "provider_bad_request"
    fake_host.down = True
    response = await api.post(f"{BASE}/providers/{provider['id']}/test", json={}, headers=auth_headers())
    assert (response.status_code, response.json()) == (503, {"detail": "host_unavailable"})


async def test_models_are_filtered_through_the_host_and_shaped_here(api: AsyncClient, fake_host: FakeHost) -> None:
    provider = await _with_key(api, "anthropic")
    fake_host.models_answer = {
        "models": [
            {"id": "a", "name": "Model A", "serves": ["summary", "transcription", "nonsense"]},
            {"id": ""},
            {"nope": 1},
            "plain-id",
            {"id": "x" * 300},
        ],
        "serves": ["transcription", "summary"],
        "starter": "a",
        "cached": True,
        "fetched_at": "2026-11-16T10:00:00+00:00",
        "secret": KEY,
    }
    response = await api.get(
        f"{BASE}/providers/{provider['id']}/models?capability=summary&refresh=true", headers=auth_headers()
    )
    assert response.json() == {
        # Anthropic is offered for summary only: whatever else the list could do is not claimed.
        "models": [
            {"id": "a", "label": "Model A", "serves": ["summary"]},
            {"id": "plain-id", "label": None, "serves": []},
        ],
        "starter": "a",
        "from_cache": True,
        "fetched_at": "2026-11-16T10:00:00+00:00",
        "manual_entry": False,
        "error_class": None,
        "serves": ["summary"],
    }
    body = [call for call in fake_host.calls if call[1] == "/v1/providers/models"][-1][2]
    assert body["refresh"] is True and body["capability"] == "summary" and "key" not in body
    assert "allow_local" not in body
    fake_host.models_answer = {"models": [{"id": "a"}], "starter": "not-listed"}
    unlisted = (
        await api.get(f"{BASE}/providers/{provider['id']}/models?capability=summary", headers=auth_headers())
    ).json()
    assert unlisted["starter"] is None  # a starter outside the list is dropped
    fake_host.models_answer = {"models": []}
    empty = (
        await api.get(f"{BASE}/providers/{provider['id']}/models?capability=summary", headers=auth_headers())
    ).json()
    assert (empty["manual_entry"], empty["serves"]) == (True, [])
    fake_host.models_status = 502
    fake_host.models_answer = {"error": {"code": "provider_unavailable", "retryable": True, "cause": "connect"}}
    failed = (
        await api.get(f"{BASE}/providers/{provider['id']}/models?capability=summary", headers=auth_headers())
    ).json()
    assert (failed["manual_entry"], failed["error_class"], failed["models"]) == (True, "provider_unavailable", [])
    fake_host.models_status = 503  # a locked keychain is a classified answer, not a missing host
    fake_host.models_answer = {"error": {"code": "secret_unavailable"}}
    locked = (
        await api.get(f"{BASE}/providers/{provider['id']}/models?capability=summary", headers=auth_headers())
    ).json()
    assert (locked["error_class"], locked["manual_entry"]) == ("secret_unavailable", True)
    assert (
        await api.get(f"{BASE}/providers/{provider['id']}/models?capability=transcription", headers=auth_headers())
    ).status_code == 422
    assert (await api.get(f"{BASE}/providers/{provider['id']}/models", headers=auth_headers())).status_code == 422


async def test_gemini_lists_serve_summary_only_and_fixed_model_providers_follow_the_matrix(
    api: AsyncClient, fake_host: FakeHost
) -> None:
    gemini = await _with_key(api, "gemini")
    fake_host.models_answer = {
        "models": [{"id": "gemini-3.1-flash-lite", "name": "x", "serves": ["summary"]}],
        "serves": ["summary"],
    }
    listed = (
        await api.get(f"{BASE}/providers/{gemini['id']}/models?capability=summary", headers=auth_headers())
    ).json()
    assert listed["serves"] == ["summary"] and listed["models"][0]["serves"] == ["summary"]
    assert (
        await api.get(f"{BASE}/providers/{gemini['id']}/models?capability=transcription", headers=auth_headers())
    ).status_code == 422  # Gemini has no transcription pair at all
    deepgram = await _with_key(api, "deepgram")
    fake_host.models_answer = {"models": []}  # one fixed model per process: nothing to list
    fixed = (
        await api.get(f"{BASE}/providers/{deepgram['id']}/models?capability=transcription", headers=auth_headers())
    ).json()
    assert fixed["serves"] == ["transcription", "diarization"]


async def test_local_servers_are_marked_for_the_host_as_local_apps(api: AsyncClient, fake_host: FakeHost) -> None:
    provider = await _create(api, "openai_compatible", base_url="http://localhost:4000/v1")
    await api.post(f"{BASE}/providers/{provider['id']}/test", json={}, headers=auth_headers())
    body = [call for call in fake_host.calls if call[1] == "/v1/providers/probe"][-1][2]
    assert body["allow_local"] is True and body["base_url"] == "http://localhost:4000/v1"
    remote = await _create(api, "openai_compatible", "Remote", base_url="https://models.example.org/v1")
    await api.post(f"{BASE}/providers/{remote['id']}/test", json={}, headers=auth_headers())
    assert "allow_local" not in [call for call in fake_host.calls if call[1] == "/v1/providers/probe"][-1][2]


async def test_status_is_a_sanitized_view_of_the_host(api: AsyncClient, fake_host: FakeHost) -> None:
    fake_host.status_answer = {
        "engines": [{"id": "asr", "port": 8001, "state": "running", "log": "/Users/x"}, {"id": 3}, "junk"],
        "secret_store": "keychain",
        "management_token": "leak",
    }
    response = await api.get(f"{BASE}/status", headers=auth_headers())
    assert response.json() == {"engines": [{"id": "asr", "port": 8001, "state": "running"}], "secret_store": "keychain"}
    fake_host.down = True
    down = await api.get(f"{BASE}/status", headers=auth_headers())
    assert (down.status_code, down.json()) == (503, {"detail": "host_unavailable"})


async def test_the_management_token_never_reaches_a_response(api: AsyncClient, fake_host: FakeHost) -> None:
    from tests.engines.conftest import MANAGEMENT_TOKEN

    provider = await _with_key(api, "anthropic")
    texts = [
        (await api.get(f"{BASE}/status", headers=auth_headers())).text,
        (await api.post(f"{BASE}/providers/{provider['id']}/test", json={}, headers=auth_headers())).text,
    ]
    fake_host.down = True
    texts.append((await api.get(f"{BASE}/status", headers=auth_headers())).text)
    assert all(MANAGEMENT_TOKEN not in text_ for text_ in texts)


# --- ChatGPT plan: account sign-in, no key ---------------------------------------------------------

CODE_LOGIN = {
    "state": "pending",
    "account": None,
    "plan": None,
    "error": None,
    "pending": {
        "user_code": "ABCD-1234",
        "verification_url": "https://auth.openai.com/codex/device",
        "expires_at": 1_800_000_900.0,
        "interval_s": 5,
        "slow_down": False,
    },
}
CONNECTED = {"state": "connected", "account": "owner@example.com", "plan": "plus", "pending": None, "error": None}


async def _plan(api: AsyncClient, user: str = OWNER) -> dict[str, Any]:
    return await _create(api, "chatgpt_plan", label="ChatGPT (plan)", user=user)


async def test_a_plan_provider_needs_no_key_and_has_a_fixed_address(api: AsyncClient) -> None:
    plan = await _plan(api)
    assert plan["base_url"] == "https://chatgpt.com/backend-api/codex"
    assert (plan["status"], plan["key_set"]) == ("active", False)
    headers = auth_headers()
    key = await api.put(f"{BASE}/providers/{plan['id']}/key", json={"key": "sk-whatever-123456"}, headers=headers)
    assert (key.status_code, key.json()) == (422, {"detail": "provider_has_no_key"})
    moved = await api.patch(
        f"{BASE}/providers/{plan['id']}", json={"base_url": "https://api.example.com/v1"}, headers=headers
    )
    assert (moved.status_code, moved.json()) == (422, {"detail": "base_url_fixed"})


async def test_the_sign_in_runs_through_the_api_and_never_shows_a_token(api: AsyncClient, fake_host: FakeHost) -> None:
    plan = await _plan(api)
    headers, path = auth_headers(), f"{BASE}/providers/{plan['id']}/account"
    assert (await api.get(path, headers=headers)).json()["state"] == "disconnected"
    fake_host.account = CODE_LOGIN
    started = await api.post(f"{path}/start", headers=headers)
    assert started.status_code == 200 and started.headers["cache-control"] == "no-store"
    pending = started.json()["pending"]
    assert (pending["user_code"], pending["verification_url"]) == ("ABCD-1234", "https://auth.openai.com/codex/device")
    assert pending["expires_at"].startswith("2027-01-15") and pending["interval_s"] == 5
    fake_host.account = CONNECTED
    done = (await api.post(f"{path}/poll", headers=headers)).json()
    assert done == {
        "state": "connected", "account": "owner@example.com", "plan": "plus", "pending": None, "error": None,
        "reverted_processes": [],
    }  # fmt: skip
    assert [(m, p) for m, p, _ in fake_host.calls if "oauth" in p] == [
        ("GET", "/v1/oauth/chatgpt/status"),
        ("POST", "/v1/oauth/chatgpt/start"),
        ("POST", "/v1/oauth/chatgpt/poll"),
    ]


async def test_only_what_the_contract_names_comes_back_from_the_host(api: AsyncClient, fake_host: FakeHost) -> None:
    plan = await _plan(api)
    fake_host.account = {
        **CODE_LOGIN,
        "access_token": "token-leak",
        "pending": {
            **CODE_LOGIN["pending"],
            "verification_url": "https://evil.example.com/x",
            "device_auth_id": "leak",
        },
    }
    response = await api.get(f"{BASE}/providers/{plan['id']}/account", headers=auth_headers())
    assert response.json()["state"] == "disconnected" and response.json()["pending"] is None  # not an OpenAI address
    fake_host.account = {**CONNECTED, "access_token": "token-leak", "refresh_token": "leak"}
    assert "leak" not in (await api.get(f"{BASE}/providers/{plan['id']}/account", headers=auth_headers())).text


async def test_account_routes_refuse_other_kinds_and_other_owners(api: AsyncClient) -> None:
    openai = await _create(api, "openai")
    plan = await _plan(api)
    refused = await api.get(f"{BASE}/providers/{openai['id']}/account", headers=auth_headers())
    assert (refused.status_code, refused.json()) == (422, {"detail": "provider_has_no_account"})
    stolen = await api.post(f"{BASE}/providers/{plan['id']}/account/start", headers=auth_headers(OTHER))
    assert (stolen.status_code, stolen.json()) == (404, {"detail": "not_found"})


async def test_a_rate_limited_start_is_a_429(api: AsyncClient, fake_host: FakeHost) -> None:
    plan = await _plan(api)
    fake_host.account_refusal = (429, "provider_rate_limited")
    response = await api.post(f"{BASE}/providers/{plan['id']}/account/start", headers=auth_headers())
    assert (response.status_code, response.json()) == (429, {"detail": "provider_rate_limited"})


async def test_a_plan_can_only_be_chosen_while_connected_and_asks_for_the_notice(
    api: AsyncClient, fake_host: FakeHost
) -> None:
    plan = await _plan(api)
    refused = await _accepted(api, "summary", plan, "gpt-5")
    assert (refused.status_code, refused.json()) == (422, {"detail": "provider_account_missing"})
    fake_host.account = CONNECTED
    no_notice = await _choose(api, "summary", plan["id"], "gpt-5")
    assert (no_notice.status_code, no_notice.json()) == (422, {"detail": "notice_required"})
    chosen = await _accepted(api, "summary", plan, "gpt-5")
    assert chosen.status_code == 200 and chosen.json()["provider_kind"] == "chatgpt_plan"
    for capability in ("transcription", "diarization"):
        other = await _accepted(api, capability, plan, "gpt-5")
        assert (other.status_code, other.json()) == (422, {"detail": "unsupported_provider"})


async def test_the_notice_names_the_plan_and_the_unofficial_path(api: AsyncClient) -> None:
    plan = await _plan(api)
    notice = (
        await api.get(f"{BASE}/processes/summary/notice?provider_id={plan['id']}", headers=auth_headers())
    ).json()
    text = " ".join(notice["paragraphs"])
    assert notice["provider_name"] == "ChatGPT (plan)" and "https://chatgpt.com" in notice["address"]
    assert "tu plan de ChatGPT" in text and "no documenta" in text


async def test_disconnecting_forgets_the_account_and_sends_the_process_back_to_local(
    api: AsyncClient, fake_host: FakeHost
) -> None:
    plan = await _plan(api)
    fake_host.account = CONNECTED
    assert (await _accepted(api, "summary", plan, "gpt-5")).status_code == 200
    done = await api.delete(f"{BASE}/providers/{plan['id']}/account", headers=auth_headers())
    assert done.status_code == 200 and done.json()["state"] == "disconnected"
    assert done.json()["reverted_processes"] == ["summary"]
    assert fake_host.account == {"state": "disconnected"}
    processes = (await api.get(f"{BASE}/processes", headers=auth_headers())).json()
    process = next(p for p in processes if p["capability"] == "summary")
    assert process["provider_id"] is None and process["model"] == "local:default"


async def test_plan_models_are_listed_with_what_they_serve(api: AsyncClient, fake_host: FakeHost) -> None:
    plan = await _plan(api)
    fake_host.models_answer = {
        "models": [{"id": "gpt-5", "name": "GPT-5", "serves": ["summary"]}],
        "serves": ["summary"],
        "starter": "gpt-5",
        "cached": False,
        "fetched_at": "2026-11-16T10:00:00+00:00",
    }
    body = (
        await api.get(f"{BASE}/providers/{plan['id']}/models?capability=summary", headers=auth_headers())
    ).json()
    assert (body["serves"], body["starter"]) == (["summary"], "gpt-5")
    assert body["models"] == [{"id": "gpt-5", "label": "GPT-5", "serves": ["summary"]}]
    payload = next(p for m, path, p in fake_host.calls if path == "/v1/providers/models")
    assert payload["transport"] == "chatgpt-responses" and "secret_ref" not in payload
