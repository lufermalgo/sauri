"""Validation of provider base URLs (shape and SSRF policy).

Rules, in order: no whitespace or control characters; only http(s); no user info, query or fragment;
http only on loopback; no non-public IP literals; no internal-looking names; a hostname must not resolve
to a non-public address. A private LAN is not allowed: only the machine itself (loopback) and public
HTTPS hosts. The host service repeats the address check at connection time, so a name that changes its
answer after this check cannot reach an internal address.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from typing import Final
from urllib.parse import urlsplit

from app.auth.local import api_port

MAX_URL_CHARS: Final = 2048
RESOLVE_TIMEOUT_S: Final = 3.0

# Database, broker and object store of the development stack; the API's own block is derived from its port.
_INFRA_PORTS: Final = frozenset({5432, 5672, 15672, 9000, 9001})
# The block after the API port: speech, speakers and summary engines, llama-server, host service.
_BLOCK_SIZE: Final = 6
_FORBIDDEN_NAMES: Final = frozenset({"metadata", "instance-data"})
_FORBIDDEN_SUFFIXES: Final = (".internal", ".local", ".localdomain", ".lan", ".home.arpa", ".intranet", ".corp")
_NUMERIC_HOST: Final = re.compile(r"^[0-9a-fA-Fx.]+$")
_UNSAFE_CHARS: Final = re.compile(r"[\x00-\x20\x7f-\x9f\\]")


def sauri_local_ports() -> frozenset[int]:
    """Sauri's own local services: a "local provider" must not be able to point the host service back at them."""
    first = api_port()
    return _INFRA_PORTS | frozenset(range(first, first + _BLOCK_SIZE))


class BaseUrlError(ValueError):
    """The URL is rejected; ``code`` is the stable machine code returned to the caller."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _parse_ip(host: str) -> IpAddress | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _effective(address: IpAddress) -> IpAddress:
    """An IPv4-mapped IPv6 address is judged as the IPv4 address it wraps."""
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def is_loopback_name(host: str) -> bool:
    if host == "localhost":
        return True
    address = _parse_ip(host)
    return address is not None and _effective(address).is_loopback


def _public(address: IpAddress) -> bool:
    effective = _effective(address)
    return effective.is_global and not (effective.is_multicast or effective.is_reserved or effective.is_unspecified)


async def resolve_host(host: str) -> list[str]:
    """Addresses a name resolves to; an empty list when it does not resolve (replaced in tests)."""
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(loop.getaddrinfo(host, None, type=socket.SOCK_STREAM), RESOLVE_TIMEOUT_S)
    except (OSError, TimeoutError):
        return []
    return sorted({str(info[4][0]) for info in infos})


async def validate_base_url(url: str, *, allow_loopback: bool) -> str:
    """Return the normalized URL (no trailing slash) or raise ``BaseUrlError``."""
    if not url or len(url) > MAX_URL_CHARS or _UNSAFE_CHARS.search(url):
        raise BaseUrlError("invalid_base_url")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise BaseUrlError("invalid_base_url") from None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower().rstrip(".")
    if scheme not in ("http", "https") or not host:
        raise BaseUrlError("invalid_base_url")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise BaseUrlError("invalid_base_url")
    if parts.query or parts.fragment or "?" in url or "#" in url:
        raise BaseUrlError("invalid_base_url")
    if port == 0:
        raise BaseUrlError("invalid_base_url")

    if is_loopback_name(host):
        if not allow_loopback or (port or (443 if scheme == "https" else 80)) in sauri_local_ports():
            raise BaseUrlError("base_url_not_allowed")
    else:
        if scheme != "https":
            raise BaseUrlError("https_required")
        await _require_public_host(host)
    return url.rstrip("/")


async def _require_public_host(host: str) -> None:
    address = _parse_ip(host)
    if address is not None:
        if not _public(address):
            raise BaseUrlError("base_url_not_allowed")
        return
    if (
        host in _FORBIDDEN_NAMES
        or host.endswith(_FORBIDDEN_SUFFIXES)
        or "." not in host
        or _NUMERIC_HOST.fullmatch(host)  # 2130706433, 0x7f.1: forms some resolvers read as an address
    ):
        raise BaseUrlError("base_url_not_allowed")
    for text in await resolve_host(host):
        resolved = _parse_ip(text)
        if resolved is None or not _public(resolved):
            raise BaseUrlError("base_url_not_allowed")


def origin_of(url: str) -> str:
    """Canonical ``scheme://host[:port]`` of an already validated URL (default ports dropped)."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    host_text = f"[{host}]" if ":" in host else host
    port = parts.port
    if port is None or port == {"http": 80, "https": 443}[scheme]:
        return f"{scheme}://{host_text}"
    return f"{scheme}://{host_text}:{port}"
