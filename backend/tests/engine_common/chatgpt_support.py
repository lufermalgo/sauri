"""Helpers for the ChatGPT-plan tests: a scripted HTTP double, synthetic tokens and a fake clock. No network."""

from __future__ import annotations

import base64
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs

from sauri_engine_common.external.safe_http import HttpResult, SafeHttp

ACCOUNT = "acct-test-0001"
EMAIL = "owner@example.com"
NOW = 1_800_000_000.0


def fake_jwt(*, exp: float, account: str | None = ACCOUNT, email: str | None = EMAIL, plan: str | None = "plus") -> str:
    auth: dict[str, Any] = {}
    if account:
        auth["chatgpt_account_id"] = account
    if plan:
        auth["chatgpt_plan_type"] = plan
    claims: dict[str, Any] = {"exp": exp, "https://api.openai.com/auth": auth}
    if email:
        claims["https://api.openai.com/profile"] = {"email": email}

    def part(value: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{part({'alg': 'none'})}.{part(claims)}.sig-synthetic"


class Clock:
    def __init__(self, now: float = NOW) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@dataclass
class Sent:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes

    def json(self) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(self.body)
        return result

    def form(self) -> dict[str, str]:
        return {name: values[0] for name, values in parse_qs(self.body.decode()).items()}


Reply = HttpResult | Callable[[Sent], Awaitable[HttpResult]]


def reply(status: int, body: Any = None, *, retry_after: str | None = None) -> HttpResult:
    return HttpResult(status, retry_after, json.dumps(body if body is not None else {}).encode())


@dataclass
class ScriptedHttp(SafeHttp):
    """Answers by ``"METHOD path"``; a list is consumed in order and its last item repeats."""

    script: dict[str, list[Reply] | Reply] = field(default_factory=dict)
    sent: list[Sent] = field(default_factory=list)

    def __post_init__(self) -> None:
        SafeHttp.__init__(self)

    async def request(  # type: ignore[override]
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
        allow_local: bool,
        total_timeout_s: float,
        connect_timeout_s: float = 3.0,
    ) -> HttpResult:
        assert not allow_local
        assert url.startswith("https://")
        item = Sent(method, url, headers, body or b"")
        self.sent.append(item)
        path = "/" + url.split("://", 1)[1].split("/", 1)[1]
        entry = self.script.get(f"{method} {path.split('?')[0]}")
        assert entry is not None, f"unscripted call {method} {path}"
        current = (entry[0] if len(entry) == 1 else entry.pop(0)) if isinstance(entry, list) else entry
        return await current(item) if callable(current) else current

    def calls(self, method: str, path: str) -> list[Sent]:
        return [
            s
            for s in self.sent
            if s.method == method and ("/" + s.url.split("://", 1)[1].split("/", 1)[1]).split("?")[0] == path
        ]
