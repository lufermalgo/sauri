"""Authenticated, owner-scoped engines API: providers, keys, per-process choice, notices and status."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.authorization import require_sales
from app.auth.schemas import AuthenticatedUser
from app.copy.engine_notices import DEFAULT_LANGUAGE, Language
from app.engines import service
from app.engines.capability_matrix import ProcessName
from app.engines.host_client import HostClient, get_host_client
from app.engines.schemas import (
    AccountOut,
    CapabilitiesOut,
    KeyIn,
    KeyOut,
    ModelsOut,
    NoticeOut,
    ProbeIn,
    ProbeOut,
    ProcessIn,
    ProcessOut,
    ProviderCreate,
    ProviderDeleteOut,
    ProviderOut,
    ProviderUpdate,
    ProviderUpdateOut,
    StatusOut,
)
from app.infra.database import create_engine, create_session_factory
from app.infra.http_errors import SafeErrorRoute
from app.meetings.schemas import ResourceId

router = APIRouter(prefix="/api/v1/engines", tags=["engines"], route_class=SafeErrorRoute)


async def get_session() -> AsyncIterator[AsyncSession]:
    engine = create_engine()
    try:
        async with create_session_factory(engine)() as session:
            yield session
    finally:
        await engine.dispose()


Session = Annotated[AsyncSession, Depends(get_session)]
AuthorizedUser = Annotated[AuthenticatedUser, Depends(require_sales(get_session))]
Host = Annotated[HostClient, Depends(get_host_client)]


@router.get("/capabilities")
async def get_capabilities(user: AuthorizedUser) -> CapabilitiesOut:
    return service.capabilities()


@router.get("/providers")
async def list_providers(session: Session, user: AuthorizedUser) -> list[ProviderOut]:
    return await service.list_providers(session, user.id)


@router.post("/providers", status_code=status.HTTP_201_CREATED)
async def create_provider(data: ProviderCreate, session: Session, user: AuthorizedUser) -> ProviderOut:
    return await service.create_provider(session, user.id, data)


@router.get("/providers/{provider_id}")
async def get_provider(provider_id: ResourceId, session: Session, user: AuthorizedUser) -> ProviderOut:
    return await service.get_provider(session, user.id, provider_id)


@router.patch("/providers/{provider_id}")
async def update_provider(
    provider_id: ResourceId, data: ProviderUpdate, session: Session, user: AuthorizedUser
) -> ProviderUpdateOut:
    return await service.update_provider(session, user.id, provider_id, data)


@router.delete("/providers/{provider_id}")
async def delete_provider(
    provider_id: ResourceId, session: Session, user: AuthorizedUser, host: Host, response: Response
) -> ProviderDeleteOut:
    response.headers["Cache-Control"] = "no-store"
    return await service.delete_provider(session, host, user.id, provider_id)


@router.put("/providers/{provider_id}/key")
async def put_key(
    provider_id: ResourceId, data: KeyIn, session: Session, user: AuthorizedUser, host: Host, response: Response
) -> KeyOut:
    response.headers["Cache-Control"] = "no-store"
    return await service.set_key(session, host, user.id, provider_id, data.key.get_secret_value())


@router.delete("/providers/{provider_id}/key")
async def delete_key(
    provider_id: ResourceId, session: Session, user: AuthorizedUser, host: Host, response: Response
) -> KeyOut:
    response.headers["Cache-Control"] = "no-store"
    return await service.delete_key(session, host, user.id, provider_id)


@router.get("/providers/{provider_id}/account")
async def get_account(
    provider_id: ResourceId, session: Session, user: AuthorizedUser, host: Host, response: Response
) -> AccountOut:
    response.headers["Cache-Control"] = "no-store"
    return await service.account_status(session, host, user.id, provider_id)


@router.post("/providers/{provider_id}/account/start")
async def start_account(
    provider_id: ResourceId, session: Session, user: AuthorizedUser, host: Host, response: Response
) -> AccountOut:
    response.headers["Cache-Control"] = "no-store"
    return await service.account_start(session, host, user.id, provider_id)


@router.post("/providers/{provider_id}/account/poll")
async def poll_account(
    provider_id: ResourceId, session: Session, user: AuthorizedUser, host: Host, response: Response
) -> AccountOut:
    response.headers["Cache-Control"] = "no-store"
    return await service.account_poll(session, host, user.id, provider_id)


@router.delete("/providers/{provider_id}/account")
async def delete_account(
    provider_id: ResourceId, session: Session, user: AuthorizedUser, host: Host, response: Response
) -> AccountOut:
    response.headers["Cache-Control"] = "no-store"
    return await service.account_disconnect(session, host, user.id, provider_id)


@router.post("/providers/{provider_id}/test")
async def test_provider(
    provider_id: ResourceId, session: Session, user: AuthorizedUser, host: Host, data: ProbeIn | None = None
) -> ProbeOut:
    return await service.test_provider(session, host, user.id, provider_id, data or ProbeIn())


@router.get("/providers/{provider_id}/models")
async def list_models(
    provider_id: ResourceId,
    capability: ProcessName,
    session: Session,
    user: AuthorizedUser,
    host: Host,
    refresh: Annotated[bool, Query()] = False,
) -> ModelsOut:
    return await service.list_models(session, host, user.id, provider_id, capability, refresh)


@router.get("/processes")
async def list_processes(session: Session, user: AuthorizedUser) -> list[ProcessOut]:
    return await service.list_processes(session, user.id)


# The literal /notice route and the process routes share the {capability} segment; none collide.
@router.get("/processes/{capability}/notice")
async def get_notice(
    capability: ProcessName,
    provider_id: Annotated[ResourceId, Query()],
    session: Session,
    user: AuthorizedUser,
    lang: Annotated[Language, Query()] = DEFAULT_LANGUAGE,
) -> NoticeOut:
    """The notice in the portal's language (``lang``); both languages carry the same ``notice_version``."""
    return await service.get_notice(session, user.id, capability, provider_id, lang)


@router.put("/processes/{capability}")
async def put_process(
    capability: ProcessName, data: ProcessIn, session: Session, user: AuthorizedUser, host: Host
) -> ProcessOut:
    return await service.put_process(session, user.id, capability, data, host)


@router.get("/status")
async def get_status(user: AuthorizedUser, host: Host) -> StatusOut:
    return await service.get_status(host)
