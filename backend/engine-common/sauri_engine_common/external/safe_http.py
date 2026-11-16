"""Safe outbound HTTP for provider calls: address policy, pinned connections and capped bodies.

Every provider call goes through ``SafeHttp``, which is the only place that opens a connection:

- the target host is resolved once and every resolved address is classified; one forbidden address
  rejects the call (loopback, link-local, private, unspecified, multicast, cloud metadata and the
  IPv4-in-IPv6 forms of them) unless the caller declared a local app (``allow_local``), which admits
  loopback and private ranges only, never link-local or metadata;
- the connection goes to the checked address (pinned) with the original ``Host`` header and TLS name,
  so a second DNS answer cannot redirect it;
- redirects are never followed, bodies are capped, proxies in the environment are ignored;
- ``https`` is required except for loopback targets.

Failures carry a closed error class and a short cause code, never a header, a key or a provider body.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import ssl
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any, Final, Literal
from urllib.parse import urlsplit

import httpx

from sauri_engine_common.external.errors import ProviderError, classify

CONNECT_TIMEOUT_S: Final = 3.0
MAX_RESPONSE_BYTES: Final = 2 * 1024 * 1024
MAX_URL_CHARS: Final = 2048
MAX_CONNECT_ATTEMPTS: Final = 3

AddressClass = Literal["public", "loopback", "private", "blocked"]
Resolver = Callable[[str, int], Awaitable[list[str]]]
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


# --- address policy ---------------------------------------------------------------------------------


def _nets(*cidrs: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    return tuple(ipaddress.ip_network(cidr) for cidr in cidrs)


_V4_PRIVATE = _nets("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
_V4_BLOCKED = _nets(
    "0.0.0.0/8",  # "this network", includes 0.0.0.0
    "100.64.0.0/10",  # shared address space, includes the 100.100.100.200 metadata address
    "169.254.0.0/16",  # link-local, includes 169.254.169.254 and 169.254.170.2
    "192.0.0.0/24",
    "192.0.2.0/24",
    "192.88.99.0/24",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    "224.0.0.0/4",
    "240.0.0.0/4",  # reserved, includes the broadcast address
)
_V6_PRIVATE = _nets("fc00::/7")  # unique-local, includes fd00::/8
_V6_BLOCKED = _nets(
    "::/128",
    "fd00:ec2::/32",  # AWS IPv6 metadata, carved out of the unique-local range
    "fe80::/10",
    "fec0::/10",
    "ff00::/8",
    "100::/64",
    "2001::/32",  # Teredo
    "2001:db8::/32",
    "64:ff9b:1::/48",
)
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_V6_COMPAT = ipaddress.ip_network("::/96")
_LEGACY_PART = re.compile(r"(0[xX][0-9a-fA-F]*)|(0[0-7]*)|([1-9][0-9]*)")


def _classify_v4(ip: ipaddress.IPv4Address) -> AddressClass:
    if ip.is_loopback:
        return "loopback"
    if any(ip in net for net in _V4_BLOCKED):
        return "blocked"
    if any(ip in net for net in _V4_PRIVATE):
        return "private"
    return "public" if ip.is_global else "blocked"


def _embedded_v4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """The IPv4 address carried by a mapped, 6to4, NAT64 or IPv4-compatible IPv6 address."""
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip in _NAT64 or ip in _V6_COMPAT:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def classify_address(ip: IPAddress) -> AddressClass:
    """Reduce an address to public / loopback / private / blocked; anything unknown is blocked."""
    if isinstance(ip, ipaddress.IPv4Address):
        return _classify_v4(ip)
    if ip == ipaddress.IPv6Address("::1"):
        return "loopback"
    embedded = _embedded_v4(ip)
    if embedded is not None and ip != ipaddress.IPv6Address("::"):
        verdict = _classify_v4(embedded)
        # Only the plain IPv4-mapped form may keep a loopback or private verdict; a tunnel form
        # (6to4, NAT64, IPv4-compatible) that points at a non-public address is never legitimate.
        if ip.ipv4_mapped is not None or verdict == "public":
            return verdict
        return "blocked"
    if any(ip in net for net in _V6_BLOCKED):
        return "blocked"
    if any(ip in net for net in _V6_PRIVATE):
        return "private"
    return "public" if ip.is_global else "blocked"


def address_allowed(ip: IPAddress, *, allow_local: bool) -> bool:
    verdict = classify_address(ip)
    return verdict == "public" or (allow_local and verdict in ("loopback", "private"))


def parse_ip_literal(host: str) -> IPAddress | None:
    """Parse every spelling a resolver or browser would read as an IP address, or ``None`` for a name.

    Besides dotted quads and IPv6 this reads the legacy IPv4 forms (``2130706433``, ``0x7f.1``,
    ``0177.0.0.1``, ``127.1``) without depending on the C library, so the policy is the same everywhere.
    """
    text = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    if ":" in text:
        try:
            return ipaddress.IPv6Address(text)
        except ValueError:
            return None
    text = text.removesuffix(".")
    parts = text.split(".")
    if not 1 <= len(parts) <= 4:
        return None
    values: list[int] = []
    for part in parts:
        if _LEGACY_PART.fullmatch(part) is None:
            return None
        if part[:2] in ("0x", "0X"):
            values.append(int(part[2:] or "0", 16))
        elif len(part) > 1 and part.startswith("0"):
            values.append(int(part, 8))
        else:
            values.append(int(part))
    *head, last = values
    if any(value > 255 for value in head) or last >= 256 ** (5 - len(parts)):
        return None
    packed = sum(value << (8 * (3 - index)) for index, value in enumerate(head)) + last
    return ipaddress.IPv4Address(packed)


# --- target parsing and the pinned HTTP client --------------------------------------------------------


@dataclass(frozen=True)
class Target:
    scheme: str
    host: str  # lowercase, no brackets
    port: int
    path: str  # path and query, as sent
    literal: IPAddress | None

    @property
    def host_header(self) -> str:
        shown = f"[{self.host}]" if ":" in self.host else self.host
        default = 443 if self.scheme == "https" else 80
        return shown if self.port == default else f"{shown}:{self.port}"


def parse_target(url: str) -> Target:
    """Split an http(s) URL, rejecting anything a parser could read two ways."""
    if len(url) > MAX_URL_CHARS or any(ord(char) <= 0x20 or ord(char) == 0x7F or char == "\\" for char in url):
        raise ProviderError("provider_bad_request", reason="invalid_url")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise ProviderError("provider_bad_request", reason="invalid_url") from None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in ("http", "https") or not host or parts.username is not None or parts.password is not None:
        raise ProviderError("provider_bad_request", reason="invalid_url")
    if parts.fragment or "%" in host or len(host) > 253:
        raise ProviderError("provider_bad_request", reason="invalid_host")
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    return Target(
        scheme=scheme,
        host=host,
        port=port if port is not None else (443 if scheme == "https" else 80),
        path=path,
        literal=parse_ip_literal(host),
    )


async def system_resolver(host: str, port: int) -> list[str]:
    """Addresses of ``host``, IPv4 first; raises ``socket.gaierror`` when it does not resolve."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    seen: dict[str, None] = {}
    for _family, _type, _proto, _canon, sockaddr in sorted(infos, key=lambda info: info[0] != socket.AF_INET):
        seen.setdefault(str(sockaddr[0]), None)
    return list(seen)[:8]


@dataclass(frozen=True)
class HttpResult:
    status: int
    retry_after: str | None
    body: bytes


def _chain(exc: BaseException | None) -> list[BaseException]:
    chain: list[BaseException] = []
    while exc is not None and exc not in chain and len(chain) < 8:
        chain.append(exc)
        exc = exc.__cause__ or exc.__context__
    return chain


def transport_error(exc: httpx.HTTPError) -> ProviderError:
    base = classify(None, exc=exc)
    chain = _chain(exc)
    if base.code == "provider_timeout":
        reason = "timeout"
    elif any(isinstance(item, ssl.SSLError) for item in chain):
        reason = "tls_error"
    elif any(isinstance(item, ConnectionRefusedError) for item in chain):
        reason = "connection_refused"
    elif isinstance(exc, httpx.ConnectError):
        reason = "connect_failed"
    else:
        reason = "connection_lost"
    return ProviderError(base.code, reason=reason)


class SafeHttp:
    """The only outbound HTTP path of this module (see the module docstring for the guarantees)."""

    def __init__(self, resolver: Resolver = system_resolver, ssl_context: ssl.SSLContext | None = None) -> None:
        self._resolver = resolver
        self._ssl_context = ssl_context

    async def _addresses(self, target: Target, *, allow_local: bool) -> list[IPAddress]:
        if target.literal is not None:
            candidates: list[IPAddress] = [target.literal]
        else:
            try:
                resolved = await self._resolver(target.host, target.port)
            except (socket.gaierror, UnicodeError):
                raise ProviderError("provider_unavailable", reason="name_not_resolved") from None
            candidates = []
            for text in resolved:
                try:
                    candidates.append(ipaddress.ip_address(text))
                except ValueError:  # includes scoped IPv6 answers
                    raise ProviderError("provider_bad_request", reason="address_not_allowed") from None
            if not candidates:
                raise ProviderError("provider_unavailable", reason="name_not_resolved")
        # One forbidden address rejects the call: no choosing among mixed answers.
        if not all(address_allowed(ip, allow_local=allow_local) for ip in candidates):
            raise ProviderError("provider_bad_request", reason="address_not_allowed")
        if target.scheme == "http" and not all(classify_address(ip) == "loopback" for ip in candidates):
            raise ProviderError("provider_bad_request", reason="https_required")
        return candidates

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
        allow_local: bool,
        total_timeout_s: float,
        connect_timeout_s: float = CONNECT_TIMEOUT_S,
    ) -> HttpResult:
        try:
            async with asyncio.timeout(total_timeout_s):
                target = parse_target(url)
                addresses = await self._addresses(target, allow_local=allow_local)
                return await self._send(method, target, addresses, headers, body, total_timeout_s, connect_timeout_s)
        except TimeoutError:
            raise ProviderError("provider_timeout", reason="timeout") from None

    async def _connect(
        self,
        stack: AsyncExitStack,
        method: str,
        target: Target,
        addresses: list[IPAddress],
        headers: dict[str, str],
        body: bytes | None,
        timeout: httpx.Timeout,
    ) -> httpx.Response:
        """Open the response on the first checked address that accepts a connection.

        The client and the stream are released by ``stack``, so closing it closes the connection.
        """
        send_headers = {**headers, "Host": target.host_header, "Accept-Encoding": "identity"}
        extensions: dict[str, Any] = {}
        if target.scheme == "https" and target.literal is None:
            extensions["sni_hostname"] = target.host  # TLS name and certificate check use the original name
        last: httpx.HTTPError | None = None
        for ip in addresses[:MAX_CONNECT_ATTEMPTS]:
            shown = f"[{ip}]" if ip.version == 6 else str(ip)
            pinned = f"{target.scheme}://{shown}:{target.port}{target.path}"
            attempt = AsyncExitStack()
            try:
                # trust_env=False: no proxy or CA override from the environment can bypass the pin.
                client = await attempt.enter_async_context(
                    httpx.AsyncClient(
                        timeout=timeout,
                        follow_redirects=False,
                        trust_env=False,
                        verify=self._ssl_context if self._ssl_context is not None else True,
                        limits=httpx.Limits(max_connections=1),
                    )
                )
                response = await attempt.enter_async_context(
                    client.stream(method, pinned, headers=send_headers, content=body, extensions=extensions)
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                await attempt.aclose()
                last = exc  # nothing was sent: try the next checked address
                continue
            except httpx.HTTPError as exc:
                await attempt.aclose()
                raise transport_error(exc) from None
            except BaseException:
                await attempt.aclose()
                raise
            stack.push_async_callback(attempt.aclose)
            return response
        assert last is not None
        raise transport_error(last)

    async def _send(
        self,
        method: str,
        target: Target,
        addresses: list[IPAddress],
        headers: dict[str, str],
        body: bytes | None,
        total_timeout_s: float,
        connect_timeout_s: float,
    ) -> HttpResult:
        timeout = httpx.Timeout(total_timeout_s, connect=connect_timeout_s)
        async with AsyncExitStack() as stack:
            response = await self._connect(stack, method, target, addresses, headers, body, timeout)
            try:
                return await _read_capped(response)
            except httpx.HTTPError as exc:
                raise transport_error(exc) from None

    @asynccontextmanager
    async def open_stream(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
        allow_local: bool,
        read_timeout_s: float,
        connect_timeout_s: float = CONNECT_TIMEOUT_S,
    ) -> AsyncIterator[HttpStream]:
        """Send the request and yield the response before its body is read.

        Same address policy, pinning and no-redirect guarantees as ``request``. Leaving the block, by return,
        error or cancellation, closes the connection to the provider. The caller owns the overall deadline.
        """
        target = parse_target(url)
        addresses = await self._addresses(target, allow_local=allow_local)
        timeout = httpx.Timeout(read_timeout_s, connect=connect_timeout_s)
        async with AsyncExitStack() as stack:
            response = await self._connect(stack, method, target, addresses, headers, body, timeout)
            yield HttpStream(response)


class HttpStream:
    """A response whose body is read on demand; it exists only inside ``SafeHttp.open_stream``."""

    def __init__(self, response: httpx.Response) -> None:
        self._response = response
        self.status = response.status_code
        self.retry_after = response.headers.get("retry-after")
        self.content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()

    async def read_capped(self, limit: int) -> bytes:
        """The body up to ``limit`` bytes; anything beyond is dropped (error bodies are only hints)."""
        chunks: list[bytes] = []
        size = 0
        try:
            async for chunk in self._response.aiter_bytes():
                chunks.append(chunk[: limit - size])
                size += len(chunks[-1])
                if size >= limit:
                    break
        except httpx.HTTPError as exc:
            raise transport_error(exc) from None
        return b"".join(chunks)

    async def iter_bytes(self) -> AsyncGenerator[bytes, None]:
        """Raw body chunks. A connection that breaks mid-body is ``provider_unavailable`` / ``stream_cut``."""
        try:
            async for chunk in self._response.aiter_bytes():
                yield chunk
        except httpx.HTTPError as exc:
            error = transport_error(exc)
            raise ProviderError(
                error.code, reason=error.reason if error.code == "provider_timeout" else "stream_cut"
            ) from None


async def _read_capped(response: httpx.Response) -> HttpResult:
    declared = response.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
        raise ProviderError("provider_bad_request", reason="response_too_large")
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise ProviderError("provider_bad_request", reason="response_too_large")
        chunks.append(chunk)
    return HttpResult(response.status_code, response.headers.get("retry-after"), b"".join(chunks))
