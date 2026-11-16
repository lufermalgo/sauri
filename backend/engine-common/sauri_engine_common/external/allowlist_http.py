"""``SafeHttp`` restricted to a fixed set of HTTPS hosts.

Used by the ChatGPT-plan sign-in and adapter: the bearer token of the user's account must never reach any
host other than the two the sign-in is issued for, whatever a route or a response says. Every guarantee of
``SafeHttp`` (resolved-address policy, pinning, no redirects, capped bodies) still applies; this class only
refuses a URL before anything is resolved or sent.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sauri_engine_common.external.errors import ProviderError
from sauri_engine_common.external.safe_http import HttpResult, HttpStream, SafeHttp, parse_target


class AllowlistedHttp(SafeHttp):
    def __init__(self, allowed_hosts: frozenset[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._allowed_hosts = frozenset(host.lower() for host in allowed_hosts)

    def _check(self, url: str, allow_local: bool) -> None:
        target = parse_target(url)
        if allow_local or target.scheme != "https" or target.host not in self._allowed_hosts:
            raise ProviderError("provider_bad_request", reason="host_not_allowed")

    async def request(self, method: str, url: str, **kwargs: Any) -> HttpResult:
        self._check(url, bool(kwargs.get("allow_local")))
        return await super().request(method, url, **kwargs)

    @asynccontextmanager
    async def open_stream(self, method: str, url: str, **kwargs: Any) -> AsyncIterator[HttpStream]:
        self._check(url, bool(kwargs.get("allow_local")))
        async with super().open_stream(method, url, **kwargs) as stream:
            yield stream
