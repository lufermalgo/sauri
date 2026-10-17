"""Canonical request hashing for persistent speaker-review writes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def canonical_request_hash(request: Mapping[str, Any]) -> str:
    """Hash request fields deterministically, excluding the transport key."""
    payload = {key: value for key, value in request.items() if key != "idempotency_key"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
