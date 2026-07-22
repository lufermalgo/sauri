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
    - "cloud": cloud provider with an encrypted channel (Req. 2.3).

    Also reads DIARIZATION_LOCAL_URL for the local provider (required, Req. 2.6).

    Raises:
        ValueError: If DIARIZATION_PROVIDER has an unrecognized value (Req. 2.5),
            or if the local provider is selected and DIARIZATION_LOCAL_URL is
            missing or empty (Req. 2.6).
    """
    raw = os.environ.get("DIARIZATION_PROVIDER", "")
    provider = raw.strip().lower()

    if provider in ("", "local"):
        from app.diarization.local_provider import LocalProvider

        url = os.environ.get("DIARIZATION_LOCAL_URL", "")
        if not url or not url.strip():
            raise ValueError(
                "DIARIZATION_LOCAL_URL is not defined or is empty; "
                "it is required for the local diarization provider"
            )
        return LocalProvider(url=url.strip())
    elif provider == "cloud":
        from app.diarization.cloud_provider import CloudProvider

        return CloudProvider()
    else:
        raise ValueError(f"Invalid DIARIZATION_PROVIDER: '{raw.strip()}'")
