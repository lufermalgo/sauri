"""Create short-lived, recording-scoped capabilities for native inference engines."""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from pathlib import Path

CAPABILITY_TTL_SECONDS = 60


def create_recording_capability(audio_ref: str) -> str:
    """Sign one object reference with the backend-only capability key."""
    key_path = Path(
        os.environ.get(
            "SAURI_RECORDING_CAPABILITY_KEY_FILE",
            Path.home() / ".config" / "sauri" / "recording_capability_key",
        )
    )
    try:
        secret = key_path.read_bytes()
    except OSError as exc:
        raise RuntimeError("Recording capability key is unavailable") from exc
    if not secret:
        raise RuntimeError("Recording capability key is empty")
    expires_at = int(time.time()) + CAPABILITY_TTL_SECONDS
    message = f"{audio_ref}\n{expires_at}".encode()
    signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return f"{expires_at}.{signature}"
