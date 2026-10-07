"""DiarizationEngine factory by configuration.

Selects the active Diarization_Provider via the DIARIZATION_PROVIDER
environment variable (Req. 2.1).

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
"""

from __future__ import annotations

import os

from app.diarization.diarization_engine import DiarizationEngine


def create_diarization_engine() -> DiarizationEngine:
    """Creates the DiarizationEngine implementation configured by environment.

    Reads the DIARIZATION_PROVIDER environment variable (case-insensitive, stripped):
    - "local" or absent/empty: local provider based on diar-engine (Req. 2.2, 2.4).
    - all other values, including "cloud": rejected before importing a provider.

    Also reads DIARIZATION_LOCAL_URL for the local provider (required, Req. 2.6).

    Raises:
        ValueError: If DIARIZATION_PROVIDER is not local (Req. 2.5), or if
            DIARIZATION_LOCAL_URL is missing or empty (Req. 2.6).
    """
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
