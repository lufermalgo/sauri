"""Per-attempt route resolution and the local fallback, shared by the processing workers.

``resolve_route`` reads the owner's process setting, the provider and the privacy consent from PostgreSQL
on every attempt, so a change applies to the next attempt without restarting anything. It never reads a key:
the host gateway reads it from the host secret store. ``call_with_fallback`` runs one call and, only for a
transient provider failure with the owner's fallback enabled, one second call to the local engine.

Rules (design.md, properties 1, 2, 14):

* No setting row, or a local setting: the route is ``None`` (or a local route naming ``local:<id>``): the
  local engine, exactly as before engines were selectable, and nothing leaves the machine.
* An external route is built only from an enabled provider that the matrix offers for the process and a
  consent of the current notice version for exactly (owner, process, provider); otherwise
  ``ProviderError("consent_missing")`` and no gateway call.
* The only second call is to the local engine, after any provider failure except the ones that need the owner
  to act (rejected sign-in or key, missing consent, a route the origin refuses, an unreadable secret, an
  unsupported pair): those never change engine. A provider that answers something unusable (invalid output,
  a refused request, an unavailable model) falls back too, with the class recorded as the reason. No
  external-to-external chain exists.

The helpers are generic over the process: transcription uses them first, and summaries and speakers reuse
``resolve_route`` and ``call_with_fallback`` unchanged.
"""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeVar

# The API image carries engine-common next to the app (``COPY . .``) but does not install it: make the shared
# route contract importable here. Appended, never inserted, so nothing it contains shadows another package.
_ENGINE_COMMON: Final = Path(__file__).resolve().parents[2] / "engine-common"
if _ENGINE_COMMON.is_dir() and str(_ENGINE_COMMON) not in sys.path:
    sys.path.append(str(_ENGINE_COMMON))

from sauri_engine_common.external.errors import ProviderError  # noqa: E402
from sauri_engine_common.route import (  # noqa: E402
    LOCAL_KIND,
    ROUTE_HEADER,
    Capability,
    Route,
    RouteTimeouts,
    encode_route,
)
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.copy.engine_notices import NOTICE_VERSIONS  # noqa: E402
from app.engines import capability_matrix as matrix  # noqa: E402
from app.infra.models import EnginePrivacyConsent, EngineProcessSetting, EngineProvider  # noqa: E402

T = TypeVar("T")

LOCAL_DEFAULT_MODEL: Final = "local:default"
# Failures the owner has to fix (reconnect, consent, settings): running the local engine would hide them.
NO_FALLBACK: Final = frozenset(
    {"provider_auth", "consent_missing", "origin_mismatch", "secret_unavailable", "provider_unsupported"}
)
# Ceiling of one external attempt, below ENGINE_CALL_TIMEOUT_S so a local fallback keeps time to run.
EXTERNAL_TOTAL_S: Final = 600.0

__all__ = [
    "ROUTE_HEADER",
    "ProviderError",
    "Provenance",
    "ResolvedRoute",
    "Route",
    "call_with_fallback",
    "encode_route",
    "is_external",
    "resolve_route",
]


@dataclass(frozen=True)
class Provenance:
    """Which engine really produced a result; never content, keys or paths."""

    engine_name: str | None
    engine_model: str | None
    external: bool
    fallback_reason: str | None = None  # error class that sent a transient failure to the local engine


@dataclass(frozen=True)
class ResolvedRoute:
    """``route`` is what to call first (``None`` = the default local engine, no header).

    ``local_fallback`` is true only when the owner enabled it and a local engine can answer.
    ``local_route`` is the local route to use for that second call (``None`` = the default local engine).
    """

    route: Route | None
    local_fallback: bool = False
    local_route: Route | None = None

    def __post_init__(self) -> None:
        if self.local_route is not None and self.local_route.kind != LOCAL_KIND:
            raise ValueError("the fallback route must be local")


def is_external(route: Route | None) -> bool:
    return route is not None and route.kind != LOCAL_KIND


def _local_route(capability: Capability, model: str) -> Route | None:
    if model == LOCAL_DEFAULT_MODEL:
        return None  # the gateway's built-in model: no header, exactly as before
    return Route(
        version=1, capability=capability, kind=LOCAL_KIND, transport=None, base_url=None, model=model,
        secret_ref=None, consent_version=None,
    )


async def resolve_route(session: AsyncSession, owner_id: str, capability: Capability) -> ResolvedRoute:
    """The route for this owner and process, read now. Raises ``ProviderError("consent_missing")`` when an
    external choice has no consent for the current notice, and ``provider_unsupported`` for a pair the
    matrix does not offer."""
    setting = await session.get(EngineProcessSetting, (owner_id, capability))
    if setting is None:
        return ResolvedRoute(None)
    if setting.provider_id is None:
        return ResolvedRoute(_local_route(capability, setting.model))
    provider = await session.scalar(
        select(EngineProvider).where(EngineProvider.id == setting.provider_id, EngineProvider.owner_id == owner_id)
    )
    if provider is None or not provider.enabled:
        # Saving a change already returns the process to local; a race never sends data out.
        return ResolvedRoute(None)
    support = matrix.get_support(provider.kind, capability)
    if support is None or not matrix.is_offered(provider.kind, capability) or provider.base_url is None:
        raise ProviderError("provider_unsupported")
    consent = await session.scalar(
        select(EnginePrivacyConsent).where(
            EnginePrivacyConsent.owner_id == owner_id,
            EnginePrivacyConsent.capability == capability,
            EnginePrivacyConsent.provider_id == provider.id,
            EnginePrivacyConsent.revoked_at.is_(None),
            EnginePrivacyConsent.notice_version == NOTICE_VERSIONS[capability],
        )
    )
    if consent is None:
        raise ProviderError("consent_missing")
    route = Route(
        version=1,
        capability=capability,
        kind=provider.kind,
        transport=support.transport,
        base_url=provider.base_url,
        model=setting.model,
        secret_ref=provider.secret_ref,
        consent_version=consent.notice_version,
        timeouts=RouteTimeouts(total_s=EXTERNAL_TOTAL_S),
    )
    return ResolvedRoute(route, local_fallback=setting.local_fallback)


async def call_with_fallback(
    resolved: ResolvedRoute,
    call: Callable[[Route | None], Awaitable[T]],
    identify: Callable[[T], tuple[str | None, str | None]],
) -> tuple[T, Provenance]:
    """Run ``call(route)``; on a provider failure that does not need the owner (``NO_FALLBACK``) with fallback
    enabled, run ``call`` once on the local engine. ``identify`` returns (engine name, engine model) from a
    result, so the provenance is what the engine reported, never what was asked for."""
    external = is_external(resolved.route)
    reason: str | None = None
    try:
        value = await call(resolved.route)
    except ProviderError as error:
        if not (external and error.code not in NO_FALLBACK and resolved.local_fallback):
            raise
        reason = error.code
    else:
        name, model = identify(value)
        return value, Provenance(name, model, external)
    value = await call(resolved.local_route)
    name, model = identify(value)
    return value, Provenance(name, model, False, reason)
