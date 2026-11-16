"""Per-process route contract between the worker and the host gateways (``X-Sauri-Route``).

The header carries the provider, model, secret reference and consent version, never keys or
meeting content. ``decode_route`` returns ``None`` when the header is absent, which means the
local engine, exactly as before this contract existed.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Final, Literal, Protocol, cast, get_args
from urllib.parse import urlsplit

from sauri_engine_common.external.errors import ProviderError
from sauri_engine_common.secrets import REF_PATTERN, SecretRecord

ROUTE_HEADER: Final = "X-Sauri-Route"
MAX_HEADER_BYTES: Final = 4096
MAX_TIMEOUT_S: Final = 86400.0

Capability = Literal["transcription", "diarization", "summary", "chat"]
Transport = Literal[
    "openai-chat", "anthropic-messages", "chatgpt-responses", "openai-audio", "assemblyai", "deepgram"
]
CAPABILITIES: Final = frozenset(get_args(Capability))
TRANSPORTS: Final = frozenset(get_args(Transport))
LOCAL_KIND: Final = "local"

_LOOPBACK_NAMES: Final = frozenset({"localhost"})
_DEFAULT_PORTS: Final = {"http": 80, "https": 443}


class RouteError(ProviderError):
    """A malformed route: ``provider_bad_request`` with a short ``reason`` code."""

    def __init__(self, reason: str) -> None:
        super().__init__("provider_bad_request", reason=reason)


@dataclass(frozen=True)
class RouteTimeouts:
    connect_s: float = 10.0
    first_byte_s: float = 120.0
    idle_s: float = 60.0
    total_s: float = 900.0


@dataclass(frozen=True)
class Route:
    version: Literal[1]
    capability: Capability
    kind: str  # "local" | "openai" | "anthropic" | ...
    transport: Transport | None  # None when kind == "local"
    base_url: str | None
    model: str  # "local:<id>" or the provider's model name
    secret_ref: str | None
    consent_version: int | None
    timeouts: RouteTimeouts = field(default_factory=RouteTimeouts)


class CapabilityMatrix(Protocol):
    """Provider kind x process support; the API owns the data (``capability_matrix.py``)."""

    def supports(self, kind: str, capability: Capability, transport: Transport) -> bool: ...


def origin_of(url: str) -> str:
    """Canonical ``scheme://host[:port]`` of an http(s) URL; default ports are dropped."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise RouteError("base_url_invalid") from None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in _DEFAULT_PORTS or not host or parts.username is not None or parts.password is not None:
        raise RouteError("base_url_invalid")
    host_text = f"[{host}]" if ":" in host else host
    if port is None or port == _DEFAULT_PORTS[scheme]:
        return f"{scheme}://{host_text}"
    return f"{scheme}://{host_text}:{port}"


def is_loopback_host(host: str) -> bool:
    if host.lower() in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def encode_route(route: Route) -> str:
    raw = json.dumps(asdict(route), separators=(",", ":"), sort_keys=True).encode()
    header = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    if len(header) > MAX_HEADER_BYTES:
        raise RouteError("route_too_large")
    return header


def _text(data: dict[str, Any], name: str, *, limit: int, optional: bool = False) -> str | None:
    value = data.get(name)
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value or len(value) > limit:
        raise RouteError("route_malformed")
    return value


def _timeouts_from(raw: object) -> RouteTimeouts:
    if raw is None:
        return RouteTimeouts()
    names = set(RouteTimeouts.__dataclass_fields__)
    if not isinstance(raw, dict) or not set(raw) <= names:
        raise RouteError("route_malformed")
    values: dict[str, float] = {}
    for name, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise RouteError("route_malformed")
        if not math.isfinite(value) or not 0 < value <= MAX_TIMEOUT_S:
            raise RouteError("route_malformed")
        values[name] = float(value)
    return RouteTimeouts(**values)


def decode_route(header: str | None) -> Route | None:
    """Parse ``X-Sauri-Route``. ``None`` means the local engine (no header)."""
    if header is None:
        return None
    if len(header) > MAX_HEADER_BYTES:
        raise RouteError("route_too_large")
    try:
        raw = base64.b64decode(header + "=" * (-len(header) % 4), altchars=b"-_", validate=True)
        data = json.loads(raw)
    except (binascii.Error, ValueError):
        raise RouteError("route_malformed") from None
    if not isinstance(data, dict):
        raise RouteError("route_malformed")
    known = {"version", "capability", "kind", "transport", "base_url", "model", "secret_ref",
             "consent_version", "timeouts"}
    if not set(data) <= known:
        raise RouteError("route_malformed")
    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise RouteError("route_malformed")
    if version != 1:
        raise RouteError("route_version_unknown")
    capability = data.get("capability")
    if not isinstance(capability, str) or capability not in CAPABILITIES:
        raise RouteError("route_capability_unsupported")
    kind = _text(data, "kind", limit=64)
    model = _text(data, "model", limit=256)
    base_url = _text(data, "base_url", limit=2048, optional=True)
    secret_ref = _text(data, "secret_ref", limit=200, optional=True)
    if secret_ref is not None and REF_PATTERN.fullmatch(secret_ref) is None:
        raise RouteError("route_malformed")
    transport = data.get("transport")
    if transport is not None and (not isinstance(transport, str) or transport not in TRANSPORTS):
        raise RouteError("route_malformed")
    consent = data.get("consent_version")
    if consent is not None and (isinstance(consent, bool) or not isinstance(consent, int) or consent < 1):
        raise RouteError("route_malformed")
    return Route(
        version=1,
        capability=cast(Capability, capability),
        kind=cast(str, kind),
        transport=cast("Transport | None", transport),
        base_url=base_url,
        model=cast(str, model),
        secret_ref=secret_ref,
        consent_version=consent,
        timeouts=_timeouts_from(data.get("timeouts")),
    )


def _require_valid_url(base_url: str | None) -> str:
    """Return the origin; HTTPS is mandatory except for loopback hosts."""
    if not base_url:
        raise RouteError("base_url_missing")
    origin = origin_of(base_url)  # also rejects malformed URLs before they are split again
    parts = urlsplit(base_url)
    if parts.fragment or parts.query:
        raise RouteError("base_url_invalid")
    if parts.scheme.lower() != "https" and not is_loopback_host(parts.hostname or ""):
        raise RouteError("https_required")
    return origin


def validate_route(route: Route, matrix: CapabilityMatrix, secret: SecretRecord | None) -> None:
    """Reject a route before any provider is contacted or any key leaves its store.

    Checks, in order: matrix support, consent, URL (HTTPS unless loopback), secret presence and
    that the secret was issued for this URL's origin. Local routes need no further checks.
    """
    if route.kind == LOCAL_KIND:
        if route.transport is not None or route.base_url is not None or route.secret_ref is not None:
            raise RouteError("local_route_has_provider_fields")
        return
    if route.transport is None or not matrix.supports(route.kind, route.capability, route.transport):
        raise ProviderError("provider_unsupported")
    if route.consent_version is None:
        raise ProviderError("consent_missing")
    origin = _require_valid_url(route.base_url)
    if route.secret_ref is None:
        return
    if secret is None:
        raise ProviderError("secret_unavailable")
    try:
        bound_origin = origin_of(secret.origin)
    except RouteError:
        raise ProviderError("origin_mismatch") from None
    if bound_origin != origin:
        raise ProviderError("origin_mismatch")
