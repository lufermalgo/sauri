"""DiarizationEngine factory by configuration.

Selects the active Diarization_Provider via the DIARIZATION_PROVIDER
environment variable (Req. 2.1).

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
"""

from __future__ import annotations

import os

from app.diarization.diarization_engine import DiarizationEngine
from app.engines.routing import ProviderError, Route, is_external


def create_diarization_engine(route: Route | None = None) -> DiarizationEngine:
    """Creates the DiarizationEngine implementation configured by environment.

    Reads the DIARIZATION_PROVIDER environment variable (case-insensitive, stripped):
    - "local" or absent/empty: local provider based on diar-engine (Req. 2.2, 2.4).
    - all other values, including "cloud": rejected before importing a provider.

    Also reads DIARIZATION_LOCAL_URL for the local provider (required, Req. 2.6).

    ``route`` is the per-attempt route the worker resolved. An external route is accepted only when it
    carries the consent version it was resolved with; the engine returned is still the gateway client, which
    sends the route to the host gateway (the gateway holds the key and makes the call). No route, or a local
    one, is the legacy behavior exactly. The legacy cloud environment value stays rejected.

    Raises:
        ProviderError: ``consent_missing`` for an external route without a consent version.
        ValueError: If DIARIZATION_PROVIDER is not local (Req. 2.5), or if
            DIARIZATION_LOCAL_URL is missing or empty (Req. 2.6).
    """
    if route is not None and is_external(route) and route.consent_version is None:
        raise ProviderError("consent_missing")
    raw = os.environ.get("DIARIZATION_PROVIDER", "")
    provider = raw.strip().lower()

    if provider not in ("", "local"):
        raise ValueError(f"Invalid DIARIZATION_PROVIDER: '{raw.strip()}'")

    url = os.environ.get("DIARIZATION_LOCAL_URL", "")
    if not url.strip():
        raise ValueError(
            "DIARIZATION_LOCAL_URL is not defined or is empty; "
            "it is required for the local diarization provider"
        )

    from app.diarization.local_provider import LocalProvider

    return LocalProvider(url=url.strip())
