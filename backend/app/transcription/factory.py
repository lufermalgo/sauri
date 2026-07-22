"""ASREngine factory by configuration.

Selects the active Transcription_Provider via the ASR_PROVIDER environment
variable without modifying the Meeting_Service code (Req. 5.2).
"""

from __future__ import annotations

import os

from app.transcription.asr_engine import ASREngine


def create_asr_engine() -> ASREngine:
    """Creates the ASREngine implementation configured by environment.

    Reads the ASR_PROVIDER environment variable (case-insensitive, stripped):
    - "local" or absent/empty: local provider based on faster-whisper (Req. 2.2, 2.4).
    - "cloud": cloud provider with an encrypted channel (Req. 2.3).

    Also reads ASR_LOCAL_URL for the local provider (required, Req. 2.6).

    Raises:
        ValueError: If ASR_PROVIDER has an unrecognized value (Req. 2.5),
            or if the local provider is selected and ASR_LOCAL_URL is
            missing or empty (Req. 2.6).
    """
    raw = os.environ.get("ASR_PROVIDER", "")
    provider = raw.strip().lower()

    if provider in ("", "local"):
        from app.transcription.local_provider import LocalProvider

        url = os.environ.get("ASR_LOCAL_URL", "")
        if not url or not url.strip():
            raise ValueError(
                "ASR_LOCAL_URL is not defined or is empty; "
                "it is required for the local provider"
            )
        return LocalProvider(url=url.strip())
    elif provider == "cloud":
        from app.transcription.cloud_provider import CloudProvider

        return CloudProvider()
    else:
        raise ValueError(f"Invalid ASR_PROVIDER: '{raw.strip()}'")
