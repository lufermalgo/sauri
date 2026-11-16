"""Provider registry, per-process engine choice and privacy consent (owner-scoped).

Every query filters by the caller's id and answers 404 for anything else, so another owner's
providers, settings and consents are indistinguishable from absent ones. Keys never touch this module's
database code: only the host service stores them, and rows keep a reference and a display hint.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any, Final
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import status
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.copy.engine_notices import DEFAULT_LANGUAGE, NOTICE_VERSIONS, Language, build_notice
from app.engines import capability_matrix as matrix
from app.engines.capability_matrix import ProcessName
from app.engines.host_client import HostClient, HostError, HostRejectedError, HostUnavailableError, valid_secret_ref
from app.engines.schemas import (
    ACCOUNT_ERRORS,
    ERROR_CLASSES,
    LOCAL_DEFAULT_MODEL,
    LOCAL_MODEL,
    AccountOut,
    AccountPendingOut,
    CapabilitiesOut,
    CapabilityOut,
    EngineStateOut,
    KeyOut,
    KindOut,
    ModelOut,
    ModelsOut,
    NoticeOut,
    ProbeIn,
    ProbeOut,
    ProcessIn,
    ProcessOut,
    ProviderCreate,
    ProviderDeleteOut,
    ProviderOut,
    ProviderStatus,
    ProviderUpdate,
    ProviderUpdateOut,
    StatusOut,
)
from app.engines.urls import BaseUrlError, is_loopback_name, origin_of, validate_base_url
from app.infra.http_errors import CONFLICT, NOT_FOUND, api_error
from app.infra.models import EnginePrivacyConsent, EngineProcessSetting, EngineProvider
from app.summaries.engine import probe_schema

logger = logging.getLogger(__name__)

MAX_PROVIDERS_PER_OWNER: Final = 50
MAX_MODELS_LISTED: Final = 500
UNPROCESSABLE: Final = 422
HOST_UNAVAILABLE: Final = "host_unavailable"
# Host codes that describe a bad request of ours, safe to hand back as a 422.
_HOST_INVALID_CODES: Final = frozenset({"invalid_secret", "invalid_secret_ref", "secret_too_large", "invalid_request"})


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    """Naive values (SQLite) are UTC; PostgreSQL returns aware ones."""
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def _host_failure(exc: HostError) -> Exception:
    """Map a host failure to a generic API error; nothing from the host's body is echoed."""
    if exc.code in _HOST_INVALID_CODES and not isinstance(exc, HostUnavailableError):
        return api_error(UNPROCESSABLE, exc.code)
    return api_error(status.HTTP_503_SERVICE_UNAVAILABLE, HOST_UNAVAILABLE)


def secret_ref_for(owner_id: str, provider_id: str) -> str:
    return f"sauri/{owner_id}/{provider_id}"


# --- Capabilities --------------------------------------------------------------------------------


def capabilities() -> CapabilitiesOut:
    kinds: list[KindOut] = []
    for kind in matrix.PROVIDER_KINDS:
        offered = [
            CapabilityOut(
                capability=capability,
                transport=support.transport,
                verified_on=support.verified_on,
            )
            for capability in matrix.VISIBLE_CAPABILITIES
            if matrix.is_offered(kind, capability) and (support := matrix.get_support(kind, capability)) is not None
        ]
        kinds.append(
            KindOut(
                kind=kind,
                default_base_url=matrix.DEFAULT_BASE_URLS[kind],
                key_required=matrix.key_needed(kind),
                auth="account" if kind in matrix.ACCOUNT_KINDS else "key",
                linkable=kind not in matrix.BLOCKED_KINDS,
                capabilities=offered,
            )
        )
    return CapabilitiesOut(
        notice_versions={name: NOTICE_VERSIONS[name] for name in matrix.VISIBLE_CAPABILITIES},
        kinds=kinds,
    )


# --- Providers -----------------------------------------------------------------------------------


def provider_status(row: EngineProvider) -> ProviderStatus:
    if not row.enabled:
        return "disabled"
    if row.base_url is None:
        return "unconfigured"
    if row.secret_ref is None and matrix.key_needed(row.kind):
        return "no_key"
    return "active"


def _visible(capabilities_used: set[str]) -> list[ProcessName]:
    return [name for name in matrix.VISIBLE_CAPABILITIES if name in capabilities_used]


def provider_out(row: EngineProvider, used_by: set[str]) -> ProviderOut:
    return ProviderOut(
        id=row.id,
        kind=row.kind,
        label=row.label,
        base_url=row.base_url,
        enabled=row.enabled,
        status=provider_status(row),
        key_set=row.secret_ref is not None,
        key_hint=row.key_hint,
        key_set_at=_aware(row.key_set_at),
        used_by=_visible(used_by),
        created_at=_aware(row.created_at),
        updated_at=_aware(row.updated_at),
    )


async def _used_by(session: AsyncSession, owner_id: str, provider_id: str | None = None) -> dict[str, set[str]]:
    query = select(EngineProcessSetting.provider_id, EngineProcessSetting.capability).where(
        EngineProcessSetting.owner_id == owner_id, EngineProcessSetting.provider_id.is_not(None)
    )
    if provider_id is not None:
        query = query.where(EngineProcessSetting.provider_id == provider_id)
    used: dict[str, set[str]] = {}
    for found_id, capability in (await session.execute(query)).all():
        if found_id is not None:
            used.setdefault(found_id, set()).add(capability)
    return used


async def _load_provider(
    session: AsyncSession, owner_id: str, provider_id: str, *, lock: bool = False
) -> EngineProvider:
    query = select(EngineProvider).where(EngineProvider.id == provider_id, EngineProvider.owner_id == owner_id)
    if lock:
        query = query.with_for_update()
    row = (await session.execute(query)).scalar_one_or_none()
    if row is None:
        raise api_error(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return row


async def list_providers(session: AsyncSession, owner_id: str) -> list[ProviderOut]:
    rows = (
        (
            await session.execute(
                select(EngineProvider)
                .where(EngineProvider.owner_id == owner_id)
                .order_by(EngineProvider.created_at, EngineProvider.id)
            )
        )
        .scalars()
        .all()
    )
    used = await _used_by(session, owner_id)
    return [provider_out(row, used.get(row.id, set())) for row in rows]


async def get_provider(session: AsyncSession, owner_id: str, provider_id: str) -> ProviderOut:
    row = await _load_provider(session, owner_id, provider_id)
    return provider_out(row, (await _used_by(session, owner_id, provider_id)).get(provider_id, set()))


async def _checked_url(kind: str, url: str) -> str:
    try:
        return await validate_base_url(url, allow_loopback=kind in matrix.LOOPBACK_KINDS)
    except BaseUrlError as exc:
        raise api_error(UNPROCESSABLE, exc.code) from None


async def _label_taken(session: AsyncSession, owner_id: str, label: str, except_id: str | None = None) -> bool:
    query = (
        select(func.count())
        .select_from(EngineProvider)
        .where(EngineProvider.owner_id == owner_id, EngineProvider.label == label)
    )
    if except_id is not None:
        query = query.where(EngineProvider.id != except_id)
    return bool((await session.execute(query)).scalar_one())


async def create_provider(session: AsyncSession, owner_id: str, data: ProviderCreate) -> ProviderOut:
    if data.kind in matrix.BLOCKED_KINDS:
        raise api_error(UNPROCESSABLE, "provider_kind_unavailable")
    raw_url = data.base_url or matrix.DEFAULT_BASE_URLS[data.kind]
    if data.kind in matrix.ACCOUNT_KINDS and raw_url != matrix.DEFAULT_BASE_URLS[data.kind]:
        raise api_error(UNPROCESSABLE, "base_url_fixed")  # the account only signs in at its own address
    if raw_url is None:
        raise api_error(UNPROCESSABLE, "base_url_required")
    base_url = await _checked_url(data.kind, raw_url)
    count = (
        await session.execute(
            select(func.count()).select_from(EngineProvider).where(EngineProvider.owner_id == owner_id)
        )
    ).scalar_one()
    if count >= MAX_PROVIDERS_PER_OWNER or await _label_taken(session, owner_id, data.label):
        raise api_error(status.HTTP_409_CONFLICT, CONFLICT)
    now = _now()
    row = EngineProvider(
        id=str(uuid4()),
        owner_id=owner_id,
        kind=data.kind,
        label=data.label,
        base_url=base_url,
        enabled=data.enabled,
        secret_ref=None,
        key_hint=None,
        key_set_at=None,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise api_error(status.HTTP_409_CONFLICT, CONFLICT) from None
    return provider_out(row, set())


async def _revert_processes(
    session: AsyncSession, owner_id: str, provider_id: str, *, delete_consents: bool = False
) -> list[ProcessName]:
    """Send every process that uses the provider back to the local engine and revoke its consents."""
    now = _now()
    settings = (
        (
            await session.execute(
                select(EngineProcessSetting)
                .where(EngineProcessSetting.owner_id == owner_id, EngineProcessSetting.provider_id == provider_id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    reverted: set[str] = set()
    for setting in settings:
        setting.provider_id = None
        setting.model = LOCAL_DEFAULT_MODEL
        setting.version += 1
        setting.updated_at = now
        reverted.add(setting.capability)
    if delete_consents:
        await session.execute(
            delete(EnginePrivacyConsent).where(
                EnginePrivacyConsent.owner_id == owner_id, EnginePrivacyConsent.provider_id == provider_id
            )
        )
    else:
        await session.execute(
            update(EnginePrivacyConsent)
            .where(
                EnginePrivacyConsent.owner_id == owner_id,
                EnginePrivacyConsent.provider_id == provider_id,
                EnginePrivacyConsent.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
    return _visible(reverted)


async def update_provider(
    session: AsyncSession, owner_id: str, provider_id: str, data: ProviderUpdate
) -> ProviderUpdateOut:
    row = await _load_provider(session, owner_id, provider_id, lock=True)
    reverted: list[ProcessName] = []
    if data.label is not None and data.label != row.label:
        if await _label_taken(session, owner_id, data.label, except_id=row.id):
            raise api_error(status.HTTP_409_CONFLICT, CONFLICT)
        row.label = data.label
    if data.base_url is not None and row.kind in matrix.ACCOUNT_KINDS and data.base_url != row.base_url:
        raise api_error(UNPROCESSABLE, "base_url_fixed")
    if data.base_url is not None:
        new_url = await _checked_url(row.kind, data.base_url)
        if row.secret_ref is not None and origin_of(new_url) != origin_of(row.base_url or new_url):
            # The stored key is bound to the old origin; replacing the key is an explicit step.
            raise api_error(status.HTTP_409_CONFLICT, "key_bound_to_origin")
        row.base_url = new_url
    if data.enabled is not None and data.enabled != row.enabled:
        row.enabled = data.enabled
        if not data.enabled:
            reverted = await _revert_processes(session, owner_id, row.id)
    row.updated_at = _now()
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise api_error(status.HTTP_409_CONFLICT, CONFLICT) from None
    used = (await _used_by(session, owner_id, row.id)).get(row.id, set())
    return ProviderUpdateOut(**provider_out(row, used).model_dump(), reverted_processes=reverted)


async def delete_provider(
    session: AsyncSession, host: HostClient, owner_id: str, provider_id: str
) -> ProviderDeleteOut:
    row = await _load_provider(session, owner_id, provider_id)
    secret_ref = row.secret_ref
    await session.commit()  # no transaction stays open across the host call
    if secret_ref is not None:
        try:
            await host.delete_secret(secret_ref)
        except HostRejectedError as exc:
            if exc.status != status.HTTP_404_NOT_FOUND:
                raise _host_failure(exc) from None
        except HostError as exc:
            raise _host_failure(exc) from None
    row = await _load_provider(session, owner_id, provider_id, lock=True)
    reverted = await _revert_processes(session, owner_id, row.id, delete_consents=True)
    await session.delete(row)
    await session.commit()
    return ProviderDeleteOut(reverted_processes=reverted)


# --- Keys ----------------------------------------------------------------------------------------


async def set_key(session: AsyncSession, host: HostClient, owner_id: str, provider_id: str, key: str) -> KeyOut:
    row = await _load_provider(session, owner_id, provider_id)
    if row.kind in matrix.ACCOUNT_KINDS:
        raise api_error(UNPROCESSABLE, "provider_has_no_key")
    if row.base_url is None:
        raise api_error(UNPROCESSABLE, "base_url_required")
    ref = secret_ref_for(owner_id, row.id)
    if not valid_secret_ref(ref):
        raise api_error(UNPROCESSABLE, "invalid_secret_ref")
    origin = origin_of(row.base_url)
    await session.commit()
    try:
        hint = await host.put_secret(ref, key, origin)
    except HostError as exc:
        raise _host_failure(exc) from None
    row = await _load_provider(session, owner_id, provider_id, lock=True)
    row.secret_ref = ref
    row.key_hint = hint
    row.key_set_at = row.updated_at = _now()
    await session.commit()
    return KeyOut(key_set=True, key_hint=hint)


async def delete_key(session: AsyncSession, host: HostClient, owner_id: str, provider_id: str) -> KeyOut:
    row = await _load_provider(session, owner_id, provider_id)
    ref = row.secret_ref
    await session.commit()
    if ref is None:
        return KeyOut(key_set=False, key_hint=None)
    try:
        await host.delete_secret(ref)
    except HostRejectedError as exc:
        if exc.status != status.HTTP_404_NOT_FOUND:
            raise _host_failure(exc) from None
    except HostError as exc:
        raise _host_failure(exc) from None
    row = await _load_provider(session, owner_id, provider_id, lock=True)
    row.secret_ref = None
    row.key_hint = None
    row.key_set_at = None
    row.updated_at = _now()
    reverted: list[ProcessName] = []
    if matrix.key_needed(row.kind):
        reverted = await _revert_processes(session, owner_id, row.id)
    await session.commit()
    return KeyOut(key_set=False, key_hint=None, reverted_processes=reverted)


# --- Connection test and model list (proxied to the host service) -------------------------------


def _host_payload(row: EngineProvider, capability: str | None) -> dict[str, Any]:
    transport = matrix.probe_transport(row.kind, capability)
    if transport is None or row.base_url is None:
        raise api_error(UNPROCESSABLE, "unsupported_provider")
    payload: dict[str, Any] = {"kind": row.kind, "transport": transport, "base_url": row.base_url}
    if is_loopback_name(urlsplit(row.base_url).hostname or ""):
        payload["allow_local"] = True  # the host admits loopback only for an app on this computer
    if row.secret_ref is not None:
        payload["secret_ref"] = row.secret_ref
    if capability is not None:
        payload["capability"] = capability
    return payload


def _error_class(value: object, default: str) -> str:
    return value if isinstance(value, str) and value in ERROR_CLASSES else default


async def test_provider(
    session: AsyncSession, host: HostClient, owner_id: str, provider_id: str, data: ProbeIn
) -> ProbeOut:
    row = await _load_provider(session, owner_id, provider_id)
    if data.capability is not None and matrix.get_support(row.kind, data.capability) is None:
        raise api_error(UNPROCESSABLE, "unsupported_provider")
    payload = _host_payload(row, data.capability)
    if data.capability == "summary":
        # Test what a real summary will meet: the model chosen for the process (when it is this provider's)
        # with the real summary schema, so an incompatible model shows up before a meeting.
        chosen = await session.scalar(
            select(EngineProcessSetting.model).where(
                EngineProcessSetting.owner_id == owner_id,
                EngineProcessSetting.capability == "summary",
                EngineProcessSetting.provider_id == row.id,
            )
        )
        if chosen:
            payload["model"] = chosen
        payload["response_schema"] = probe_schema()
    await session.commit()
    try:
        raw = await host.probe(payload)
    except HostRejectedError as exc:
        return ProbeOut(ok=False, error_class=_error_class(exc.code, "provider_bad_request"))
    except HostError as exc:
        raise _host_failure(exc) from None
    ok = raw.get("ok") is True
    latency = raw.get("latency_ms")
    schema_ok = raw.get("json_schema_ok")
    schema_model = raw.get("schema_model")
    schema_class = raw.get("schema_error_class")
    return ProbeOut(
        ok=ok,
        latency_ms=latency if isinstance(latency, int) and not isinstance(latency, bool) and latency >= 0 else None,
        error_class=None if ok else _error_class(raw.get("error_class"), "provider_unavailable"),
        json_schema_ok=schema_ok if isinstance(schema_ok, bool) else None,
        schema_error_class=schema_class if ok and schema_class in ERROR_CLASSES else None,
        schema_model=schema_model if isinstance(schema_model, str) and 0 < len(schema_model) <= 200 else None,
    )


# Providers with one fixed model per process: they list nothing, so the matrix alone says what they serve.
_FIXED_MODEL_TRANSPORTS: Final = frozenset({"assemblyai", "deepgram"})


def _offered_processes(kind: str, declared: object) -> list[ProcessName]:
    """What a model (or the whole list) serves, kept to the pairs Sauri offers for this kind."""
    names = set(declared) if isinstance(declared, list) else set()
    return [name for name in matrix.VISIBLE_CAPABILITIES if name in names and matrix.is_offered(kind, name)]


def _provider_serves(kind: str, raw: dict[str, Any], models: list[ModelOut]) -> list[ProcessName]:
    offered = [name for name in matrix.VISIBLE_CAPABILITIES if matrix.is_offered(kind, name)]
    if offered and all(matrix.probe_transport(kind, name) in _FIXED_MODEL_TRANSPORTS for name in offered):
        return offered
    return _offered_processes(kind, raw.get("serves")) if models else []


async def list_models(
    session: AsyncSession,
    host: HostClient,
    owner_id: str,
    provider_id: str,
    capability: ProcessName,
    refresh: bool,
) -> ModelsOut:
    row = await _load_provider(session, owner_id, provider_id)
    if matrix.get_support(row.kind, capability) is None:
        raise api_error(UNPROCESSABLE, "unsupported_provider")
    payload = {**_host_payload(row, capability), "refresh": refresh}
    await session.commit()
    try:
        raw = await host.models(payload)
    except HostRejectedError as exc:
        return ModelsOut(
            models=[],
            starter=None,
            from_cache=False,
            fetched_at=None,
            manual_entry=True,
            error_class=_error_class(exc.code, "provider_unavailable"),
        )
    except HostError as exc:
        raise _host_failure(exc) from None
    models: list[ModelOut] = []
    listed = raw.get("models")
    for item in listed[:MAX_MODELS_LISTED] if isinstance(listed, list) else []:
        entry_id = item.get("id") if isinstance(item, dict) else item
        label = item.get("name") if isinstance(item, dict) else None
        if isinstance(entry_id, str) and 0 < len(entry_id) <= 200:
            models.append(
                ModelOut(
                    id=entry_id,
                    label=label if isinstance(label, str) and len(label) <= 200 else None,
                    serves=_offered_processes(row.kind, item.get("serves") if isinstance(item, dict) else None),
                )
            )
    fetched_at = raw.get("fetched_at")
    starter = raw.get("starter")
    return ModelsOut(
        models=models,
        starter=starter if isinstance(starter, str) and starter in {m.id for m in models} else None,
        from_cache=raw.get("cached") is True,
        fetched_at=fetched_at if isinstance(fetched_at, str) and len(fetched_at) <= 64 else None,
        manual_entry=not models,
        error_class=None,
        serves=_provider_serves(row.kind, raw, models),
    )


# --- Processes, notices and consent --------------------------------------------------------------


async def _active_consents(
    session: AsyncSession, owner_id: str, capability: str, *, lock: bool = False
) -> list[EnginePrivacyConsent]:
    query = select(EnginePrivacyConsent).where(
        EnginePrivacyConsent.owner_id == owner_id,
        EnginePrivacyConsent.capability == capability,
        EnginePrivacyConsent.revoked_at.is_(None),
    )
    if lock:
        query = query.with_for_update()
    return list((await session.execute(query)).scalars().all())


def _process_out(
    capability: ProcessName,
    setting: EngineProcessSetting | None,
    provider: EngineProvider | None,
    consent: EnginePrivacyConsent | None,
) -> ProcessOut:
    if setting is None:
        return ProcessOut(
            capability=capability,
            provider_id=None,
            provider_kind=None,
            provider_label=None,
            model=LOCAL_DEFAULT_MODEL,
            local_fallback=True,
            configured=False,
            version=0,
            updated_at=None,
            notice_version=None,
        )
    return ProcessOut(
        capability=capability,
        provider_id=setting.provider_id,
        provider_kind=provider.kind if provider else None,
        provider_label=provider.label if provider else None,
        model=setting.model,
        local_fallback=setting.local_fallback,
        configured=True,
        version=setting.version,
        updated_at=_aware(setting.updated_at),
        notice_version=consent.notice_version if consent else None,
    )


async def list_processes(session: AsyncSession, owner_id: str) -> list[ProcessOut]:
    settings = {
        row.capability: row
        for row in (
            await session.execute(select(EngineProcessSetting).where(EngineProcessSetting.owner_id == owner_id))
        ).scalars()
    }
    providers = {
        row.id: row
        for row in (await session.execute(select(EngineProvider).where(EngineProvider.owner_id == owner_id))).scalars()
    }
    consents = {
        (row.capability, row.provider_id): row
        for row in (
            await session.execute(
                select(EnginePrivacyConsent).where(
                    EnginePrivacyConsent.owner_id == owner_id, EnginePrivacyConsent.revoked_at.is_(None)
                )
            )
        ).scalars()
    }
    result: list[ProcessOut] = []
    for capability in matrix.VISIBLE_CAPABILITIES:
        setting = settings.get(capability)
        provider_id = setting.provider_id if setting else None
        result.append(
            _process_out(
                capability,
                setting,
                providers.get(provider_id) if provider_id else None,
                consents.get((capability, provider_id)) if provider_id else None,
            )
        )
    return result


async def get_notice(
    session: AsyncSession,
    owner_id: str,
    capability: ProcessName,
    provider_id: str,
    language: Language = DEFAULT_LANGUAGE,
) -> NoticeOut:
    row = await _load_provider(session, owner_id, provider_id)
    if not matrix.is_offered(row.kind, capability) or row.base_url is None:
        raise api_error(UNPROCESSABLE, "unsupported_provider")
    address = origin_of(row.base_url)
    notice = build_notice(
        capability,
        row.kind,
        address,
        runs_on_this_device=is_loopback_name(urlsplit(row.base_url).hostname or ""),
        language=language,
    )
    return NoticeOut(
        capability=capability,
        provider_id=row.id,
        provider_kind=row.kind,
        provider_name=notice.provider_name,
        address=notice.address,
        notice_version=notice.version,
        title=notice.title,
        paragraphs=list(notice.paragraphs),
    )


async def _require_signed_in(session: AsyncSession, host: HostClient, owner_id: str, provider_id: str) -> None:
    """An account provider can only be chosen while its account is connected (checked before any row lock)."""
    row = (
        await session.execute(
            select(EngineProvider).where(EngineProvider.id == provider_id, EngineProvider.owner_id == owner_id)
        )
    ).scalar_one_or_none()
    if row is None or row.kind not in matrix.ACCOUNT_KINDS:
        return
    await session.commit()  # no transaction stays open across the host call
    try:
        raw = await host.chatgpt_status()
    except HostError as exc:
        raise _host_failure(exc) from None
    if raw.get("state") != "connected":
        raise api_error(UNPROCESSABLE, "provider_account_missing")


async def put_process(
    session: AsyncSession, owner_id: str, capability: ProcessName, data: ProcessIn, host: HostClient | None = None
) -> ProcessOut:
    if host is not None and data.provider_id is not None:
        await _require_signed_in(session, host, owner_id, data.provider_id)
    provider: EngineProvider | None = None
    setting = (
        await session.execute(
            select(EngineProcessSetting)
            .where(EngineProcessSetting.owner_id == owner_id, EngineProcessSetting.capability == capability)
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = _now()
    consents = await _active_consents(session, owner_id, capability, lock=True)
    kept: EnginePrivacyConsent | None = None

    if data.provider_id is None:
        if LOCAL_MODEL.fullmatch(data.model) is None:
            raise api_error(UNPROCESSABLE, "invalid_model")
    else:
        provider = await _load_provider(session, owner_id, data.provider_id, lock=True)
        if not provider.enabled:
            raise api_error(UNPROCESSABLE, "provider_disabled")
        if not matrix.is_offered(provider.kind, capability) or provider.base_url is None:
            raise api_error(UNPROCESSABLE, "unsupported_provider")
        if provider.secret_ref is None and matrix.key_needed(provider.kind):
            raise api_error(UNPROCESSABLE, "provider_key_missing")
        if data.model.startswith("local:"):
            raise api_error(UNPROCESSABLE, "invalid_model")
        current = NOTICE_VERSIONS[capability]
        if data.notice_version is not None and data.notice_version != current:
            raise api_error(status.HTTP_409_CONFLICT, "notice_outdated")
        kept = next((c for c in consents if c.provider_id == provider.id and c.notice_version == current), None)
        if kept is None and data.notice_version is None:
            raise api_error(UNPROCESSABLE, "notice_required")

    # Consent follows the active route: everything else for this process is revoked, and a new
    # consent is recorded only when the user accepted the current notice for this provider.
    for consent in consents:
        if consent is not kept:
            consent.revoked_at = now
    await session.flush()
    if provider is not None and kept is None:
        kept = EnginePrivacyConsent(
            id=str(uuid4()),
            owner_id=owner_id,
            capability=capability,
            provider_id=provider.id,
            notice_version=NOTICE_VERSIONS[capability],
            accepted_at=now,
            revoked_at=None,
        )
        session.add(kept)

    if setting is None:
        setting = EngineProcessSetting(
            owner_id=owner_id,
            capability=capability,
            provider_id=None,
            model=data.model,
            local_fallback=data.local_fallback,
            version=1,
            updated_at=now,
        )
        session.add(setting)
    else:
        setting.version += 1
    setting.provider_id = provider.id if provider else None
    setting.model = data.model
    setting.local_fallback = data.local_fallback
    setting.updated_at = now
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise api_error(status.HTTP_409_CONFLICT, CONFLICT) from None
    return _process_out(capability, setting, provider, kept)


# --- Account sign-in (ChatGPT plan; proxied to the host service) ---------------------------------

_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_USER_CODE: Final = re.compile(r"[A-Za-z0-9-]{1,32}")
_PLAN_LABEL: Final = re.compile(r"[a-z0-9_-]{1,32}")
_VERIFICATION_PREFIX: Final = "https://auth.openai.com/"


def _account_failure(exc: HostError) -> Exception:
    """A refusal that names a provider class (rate limit, store locked) keeps it; the rest is generic."""
    if isinstance(exc, HostRejectedError) and exc.code in ERROR_CLASSES:
        limited = exc.code == "provider_rate_limited"
        return api_error(status.HTTP_429_TOO_MANY_REQUESTS if limited else status.HTTP_502_BAD_GATEWAY, exc.code)
    return _host_failure(exc)


def _account_out(raw: dict[str, Any], reverted: list[ProcessName] | None = None) -> AccountOut:
    """Built field by field from the host's answer: nothing else is passed through."""
    state = raw.get("state")
    account, plan, error = raw.get("account"), raw.get("plan"), raw.get("error")
    pending: AccountPendingOut | None = None
    found = raw.get("pending")
    if state == "pending" and isinstance(found, dict):
        code, url, expires, interval = (
            found.get("user_code"), found.get("verification_url"), found.get("expires_at"), found.get("interval_s")
        )  # fmt: skip
        if (
            isinstance(code, str) and _USER_CODE.fullmatch(code)
            and isinstance(url, str) and url.startswith(_VERIFICATION_PREFIX) and len(url) <= 200
            and isinstance(expires, int | float) and not isinstance(expires, bool)
            and isinstance(interval, int | float) and not isinstance(interval, bool)
        ):  # fmt: skip
            pending = AccountPendingOut(
                user_code=code,
                verification_url=url,
                expires_at=datetime.fromtimestamp(expires, UTC),
                interval_s=min(max(round(interval), 1), 60),
                slow_down=found.get("slow_down") is True,
            )
    clean_state = "connected" if state == "connected" else "pending" if pending is not None else "disconnected"
    return AccountOut(
        state=clean_state,
        account=account if clean_state == "connected" and isinstance(account, str) and 0 < len(account) <= 254
        and _CONTROL.search(account) is None else None,
        plan=plan if clean_state == "connected" and isinstance(plan, str) and _PLAN_LABEL.fullmatch(plan) else None,
        pending=pending,
        error=error if clean_state == "disconnected" and isinstance(error, str) and error in ACCOUNT_ERRORS else None,
        reverted_processes=reverted or [],
    )


async def _account_provider(session: AsyncSession, owner_id: str, provider_id: str) -> None:
    row = await _load_provider(session, owner_id, provider_id)
    if row.kind not in matrix.ACCOUNT_KINDS:
        raise api_error(UNPROCESSABLE, "provider_has_no_account")
    await session.commit()  # no transaction stays open across the host call


async def account_status(session: AsyncSession, host: HostClient, owner_id: str, provider_id: str) -> AccountOut:
    await _account_provider(session, owner_id, provider_id)
    try:
        return _account_out(await host.chatgpt_status())
    except HostError as exc:
        raise _account_failure(exc) from None


async def account_start(session: AsyncSession, host: HostClient, owner_id: str, provider_id: str) -> AccountOut:
    await _account_provider(session, owner_id, provider_id)
    try:
        return _account_out(await host.chatgpt_start())
    except HostError as exc:
        raise _account_failure(exc) from None


async def account_poll(session: AsyncSession, host: HostClient, owner_id: str, provider_id: str) -> AccountOut:
    await _account_provider(session, owner_id, provider_id)
    try:
        return _account_out(await host.chatgpt_poll())
    except HostError as exc:
        raise _account_failure(exc) from None


async def account_disconnect(session: AsyncSession, host: HostClient, owner_id: str, provider_id: str) -> AccountOut:
    """Forget the account on the host and send every process that used it back to the local engine."""
    await _account_provider(session, owner_id, provider_id)
    try:
        await host.chatgpt_logout()
    except HostError as exc:
        raise _account_failure(exc) from None
    await _load_provider(session, owner_id, provider_id, lock=True)
    reverted = await _revert_processes(session, owner_id, provider_id)
    await session.commit()
    return _account_out({"state": "disconnected"}, reverted)


# --- Status --------------------------------------------------------------------------------------


async def get_status(host: HostClient) -> StatusOut:
    try:
        raw = await host.engines_status()
    except HostError as exc:
        raise _host_failure(exc) from None
    engines: list[EngineStateOut] = []
    listed = raw.get("engines")
    for item in listed[:16] if isinstance(listed, list) else []:
        try:
            engines.append(EngineStateOut(id=item["id"], port=item["port"], state=item["state"]))
        except (KeyError, TypeError, ValueError):
            continue
    store = raw.get("secret_store")
    return StatusOut(engines=engines, secret_store=store if isinstance(store, str) and len(store) <= 32 else None)
