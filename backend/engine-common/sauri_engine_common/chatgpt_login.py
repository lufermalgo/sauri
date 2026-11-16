"""Sign-in with the user's ChatGPT account (device code) for the summary process, with no API key.

This copies how APX does it (the way the Codex client signs in), by the owner's decision of 2026-11-16. It is not
a documented access path and may stop working; the endpoints and the public client id below are the only things
to update when it does.

- The sign-in is Sauri's own. The Codex CLI's ``~/.codex`` is never read or written, so the two never share a
  refresh-token family.
- Tokens live only in the host secret store (macOS Keychain). The refresh token and the account facts are one
  record, the access token another, so each stays well inside the Keychain command-line limit. A refreshed
  refresh token is stored BEFORE the new access token is used.
- Refreshing is single-flight: one asyncio lock inside the process and one ``flock`` between the host service
  and the LLM gateway, which both read the same records. A caller that waited re-reads the store and uses what
  the winner saved. A refused refresh token clears the sign-in.
- Every call goes through an ``AllowlistedHttp`` (``auth.openai.com`` and ``chatgpt.com`` only).
- Nothing here returns or logs a token, a device id, a header or a provider body; failures are ``ProviderError``
  with a closed class and a short ``reason``.
"""

from __future__ import annotations

import asyncio
import base64
import fcntl
import json
import logging
import os
import re
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlencode

from sauri_engine_common.external.allowlist_http import AllowlistedHttp
from sauri_engine_common.external.errors import ProviderError, classify
from sauri_engine_common.external.safe_http import HttpResult, SafeHttp
from sauri_engine_common.secrets import SecretError, SecretRecord, SecretStore

logger = logging.getLogger("sauri.chatgpt_login")

ISSUER: Final = "https://auth.openai.com"
API_BASE: Final = "https://chatgpt.com/backend-api/codex"
ALLOWED_HOSTS: Final = frozenset({"auth.openai.com", "chatgpt.com"})
# Public client id of the Codex sign-in (the same one APX uses).
CLIENT_ID: Final = "app_EMoamEEZ73f0CkXaXp7hrann"
ORIGINATOR: Final = "sauri"
USER_AGENT: Final = "sauri-chatgpt-plan/1"
# The models endpoint hides models newer than the client version it is told.
CLIENT_VERSION: Final = "0.160.0"
REFRESH_REF: Final = "oauth/chatgpt/refresh"
ACCESS_REF: Final = "oauth/chatgpt/access"
SKEW_S: Final = 120  # refresh this long before the access token runs out
DEVICE_WINDOW_S: Final = 15 * 60
DEFAULT_INTERVAL_S: Final = 5
MIN_INTERVAL_S: Final = 3
MAX_INTERVAL_S: Final = 30
SLOW_DOWN_STEP_S: Final = 5
DEFAULT_ACCESS_TTL_S: Final = 3600
REQUEST_TIMEOUT_S: Final = 20.0
LOCK_TIMEOUT_S: Final = 40.0
LOCK_POLL_S: Final = 0.05
DEFAULT_LOCK_PATH: Final = Path.home() / ".config" / "sauri" / "chatgpt_login.lock"

# Why the last sign-in attempt did not end connected (closed set; the portal maps each to its own text).
ERROR_CODE_EXPIRED: Final = "code_expired"
ERROR_DENIED: Final = "access_denied"
ERROR_FAILED: Final = "login_failed"
ERROR_SESSION_EXPIRED: Final = "session_expired"

_REFUSED_CODES: Final = re.compile(r"invalid_grant|invalid_token|refresh_token_reused|refresh_token_expired")
_PLAN: Final = re.compile(r"[a-z0-9_-]{1,32}")
_ACCOUNT: Final = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_EMAIL: Final = re.compile(r"[^\s<>\x00-\x1f]{3,254}")
_CODE: Final = re.compile(r"[A-Za-z0-9_.:-]{1,64}")


def login_required() -> ProviderError:
    """The user has to sign in again; the portal shows «Conectar con Codex»."""
    return ProviderError("provider_auth", reason="login_required")


def claims_of(jwt: str) -> dict[str, Any]:
    """The payload of a JWT without checking its signature: only used to read facts about our own token."""
    try:
        part = jwt.split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _sub(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name)
    return value if isinstance(value, dict) else {}


@dataclass(frozen=True)
class ChatGptCredentials:
    """A usable access token and the account it belongs to."""

    token: str = field(repr=False)
    account_id: str

    def headers(self) -> dict[str, str]:
        return {
            "authorization": f"Bearer {self.token}",
            "chatgpt-account-id": self.account_id,
            "originator": ORIGINATOR,
            "user-agent": USER_AGENT,
        }


@dataclass(frozen=True)
class _Account:
    refresh_token: str = field(repr=False)
    account_id: str
    email: str | None
    plan: str | None


@dataclass(frozen=True)
class _Access:
    token: str = field(repr=False)
    expires_at: float


@dataclass
class _Pending:
    device_auth_id: str = field(repr=False)
    user_code: str
    verification_url: str
    expires_at: float
    interval_s: float
    next_poll_at: float
    slow_down: bool = False


def _record(payload: dict[str, Any], origin: str) -> SecretRecord:
    return SecretRecord(key=json.dumps(payload, separators=(",", ":")), origin=origin)


def _payload(record: SecretRecord) -> dict[str, Any]:
    try:
        data = json.loads(record.key)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _error_code(body: bytes) -> str | None:
    """A provider error code (never free text) from an OAuth or API error body."""
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    error = data.get("error")
    candidates = [error.get("code"), error.get("type")] if isinstance(error, dict) else [error, data.get("code")]
    for candidate in candidates:
        if isinstance(candidate, str) and _CODE.fullmatch(candidate):
            return candidate.lower()
    return None


def _json(result: HttpResult) -> dict[str, Any]:
    try:
        data = json.loads(result.body)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


class ChatGptLogin:
    """Device-code sign-in, token storage and refresh for one machine."""

    def __init__(
        self,
        store: SecretStore,
        http: SafeHttp | None = None,
        *,
        clock: Callable[[], float] = time.time,
        lock_path: Path = DEFAULT_LOCK_PATH,
        issuer: str = ISSUER,
    ) -> None:
        self._store = store
        self._http = http or AllowlistedHttp(ALLOWED_HOSTS)
        self._clock = clock
        self._lock_path = lock_path
        self._issuer = issuer.rstrip("/")
        self._refresh_lock = asyncio.Lock()
        self._poll_lock = asyncio.Lock()
        self._pending: _Pending | None = None
        self._last_error: str | None = None

    # --- storage ---------------------------------------------------------------------------------------

    async def _read_account(self) -> _Account | None:
        try:
            data = _payload(await asyncio.to_thread(self._store.get, REFRESH_REF))
        except SecretError:
            return None
        refresh, account = data.get("refresh_token"), data.get("account_id")
        if not isinstance(refresh, str) or not refresh or not isinstance(account, str) or not account:
            return None
        email, plan = data.get("email"), data.get("plan")
        return _Account(
            refresh, account, email if isinstance(email, str) else None, plan if isinstance(plan, str) else None
        )

    async def _read_access(self) -> _Access | None:
        try:
            data = _payload(await asyncio.to_thread(self._store.get, ACCESS_REF))
        except SecretError:
            return None
        token, expires_at = data.get("access_token"), data.get("expires_at")
        if not isinstance(token, str) or not token or isinstance(expires_at, bool):
            return None
        if not isinstance(expires_at, int | float):
            return None
        return _Access(token, float(expires_at))

    async def _clear(self) -> None:
        for ref in (ACCESS_REF, REFRESH_REF):
            try:
                await asyncio.to_thread(self._store.delete, ref)
            except SecretError:
                logger.warning("chatgpt_login_clear_failed")

    async def _save(self, tokens: dict[str, Any], previous: _Account | None) -> tuple[_Account, _Access]:
        """Store a token response: the refresh record first, then the access token."""
        access = tokens.get("access_token")
        if not isinstance(access, str) or not access:
            raise ProviderError("provider_invalid_output", reason="no_access_token")
        refresh = tokens.get("refresh_token")
        if not isinstance(refresh, str) or not refresh:
            if previous is None:
                raise ProviderError("provider_invalid_output", reason="no_refresh_token")
            refresh = previous.refresh_token
        claims = claims_of(access)
        auth, profile = _sub(claims, "https://api.openai.com/auth"), _sub(claims, "https://api.openai.com/profile")
        account_id = auth.get("chatgpt_account_id")
        if not (isinstance(account_id, str) and _ACCOUNT.fullmatch(account_id)):
            account_id = previous.account_id if previous is not None else None
        if account_id is None:
            raise ProviderError("provider_invalid_output", reason="no_account")
        email = profile.get("email")
        email = email if isinstance(email, str) and _EMAIL.fullmatch(email) else (previous.email if previous else None)
        plan = auth.get("chatgpt_plan_type")
        plan = plan if isinstance(plan, str) and _PLAN.fullmatch(plan) else (previous.plan if previous else None)
        exp, ttl = claims.get("exp"), tokens.get("expires_in")
        if isinstance(exp, int | float) and not isinstance(exp, bool):
            expires_at = float(exp)
        elif isinstance(ttl, int | float) and not isinstance(ttl, bool) and ttl > 0:
            expires_at = self._clock() + float(ttl)
        else:
            expires_at = self._clock() + DEFAULT_ACCESS_TTL_S
        account = _Account(refresh, account_id, email, plan)
        try:
            await asyncio.to_thread(
                self._store.put,
                REFRESH_REF,
                _record({"refresh_token": refresh, "account_id": account_id, "email": email, "plan": plan}, ISSUER),
            )
            await asyncio.to_thread(
                self._store.put,
                ACCESS_REF,
                _record({"access_token": access, "expires_at": expires_at}, "https://chatgpt.com"),
            )
        except SecretError:
            raise ProviderError("secret_unavailable") from None
        return account, _Access(access, expires_at)

    # --- upstream calls --------------------------------------------------------------------------------

    async def _send(self, path: str, *, body: bytes, content_type: str) -> HttpResult:
        return await self._http.request(
            "POST",
            f"{self._issuer}{path}",
            headers={"content-type": content_type, "accept": "application/json", "user-agent": USER_AGENT},
            body=body,
            allow_local=False,
            total_timeout_s=REQUEST_TIMEOUT_S,
        )

    async def _token_request(self, form: dict[str, str]) -> dict[str, Any]:
        """``POST /oauth/token``. A refused grant is ``login_required``; anything else keeps the sign-in."""
        result = await self._send(
            "/oauth/token", body=urlencode(form).encode(), content_type="application/x-www-form-urlencoded"
        )
        if 200 <= result.status < 300:
            data = _json(result)
            if isinstance(data.get("access_token"), str):
                return data
            raise ProviderError("provider_invalid_output", reason="bad_response")
        code = _error_code(result.body)
        if result.status in (401, 403) or (code is not None and _REFUSED_CODES.fullmatch(code)):
            raise login_required()
        error = classify(result.status, code, retry_after=result.retry_after)
        raise ProviderError(error.code, retry_after_s=error.retry_after_s, reason=f"token_http_{result.status}")

    # --- device sign-in --------------------------------------------------------------------------------

    async def start(self) -> dict[str, Any]:
        """Ask for a device code. The user types it at the verification address; ``poll`` finishes the sign-in."""
        result = await self._send(
            "/api/accounts/deviceauth/usercode",
            body=json.dumps({"client_id": CLIENT_ID}).encode(),
            content_type="application/json",
        )
        data = _json(result)
        user_code, device_auth_id = data.get("user_code"), data.get("device_auth_id")
        if not (200 <= result.status < 300 and isinstance(user_code, str) and isinstance(device_auth_id, str)):
            if result.status == 429:
                error = classify(429, None, retry_after=result.retry_after)
                raise ProviderError(error.code, retry_after_s=error.retry_after_s, reason="start_rate_limited")
            raise ProviderError("provider_unavailable", reason=f"start_http_{result.status}")
        if not 1 <= len(user_code) <= 32 or any(ord(char) < 0x20 for char in user_code):
            raise ProviderError("provider_invalid_output", reason="bad_response")
        raw = data.get("interval")
        interval = float(raw) if isinstance(raw, int | float) and not isinstance(raw, bool) else DEFAULT_INTERVAL_S
        interval = min(max(interval, MIN_INTERVAL_S), MAX_INTERVAL_S)
        now = self._clock()
        self._pending = _Pending(
            device_auth_id=device_auth_id,
            user_code=user_code,
            verification_url=f"{self._issuer}/codex/device",
            expires_at=now + DEVICE_WINDOW_S,
            interval_s=interval,
            next_poll_at=now + interval,
        )
        self._last_error = None
        return await self.status()

    async def poll(self) -> dict[str, Any]:
        """Advance a pending sign-in by one upstream check (at most one per interval), then report the state."""
        async with self._poll_lock:
            pending = self._pending
            if pending is not None:
                now = self._clock()
                if now >= pending.expires_at:
                    self._finish(ERROR_CODE_EXPIRED)
                elif now >= pending.next_poll_at:
                    await self._poll_once(pending)
        return await self.status()

    def _finish(self, error: str | None) -> None:
        self._pending = None
        self._last_error = error

    async def _poll_once(self, pending: _Pending) -> None:
        try:
            result = await self._send(
                "/api/accounts/deviceauth/token",
                body=json.dumps({"device_auth_id": pending.device_auth_id, "user_code": pending.user_code}).encode(),
                content_type="application/json",
            )
        except ProviderError:
            # A network error is not a verdict: keep waiting, the code is still valid until it expires.
            pending.next_poll_at = self._clock() + pending.interval_s
            return
        now = self._clock()
        code = _error_code(result.body)
        data = _json(result)
        if 200 <= result.status < 300:
            await self._complete(pending, data)
        elif code == "slow_down" or result.status == 429:
            pending.interval_s = min(pending.interval_s + SLOW_DOWN_STEP_S, MAX_INTERVAL_S)
            pending.next_poll_at = now + pending.interval_s
            pending.slow_down = True
        elif code in ("expired_token", "device_code_expired") or result.status == 410:
            self._finish(ERROR_CODE_EXPIRED)
        elif code == "access_denied":
            self._finish(ERROR_DENIED)
        elif result.status in (403, 404):  # not approved yet
            pending.next_poll_at = now + pending.interval_s
        else:
            self._finish(ERROR_FAILED)

    async def _complete(self, pending: _Pending, grant: dict[str, Any]) -> None:
        code, verifier = grant.get("authorization_code"), grant.get("code_verifier")
        if not isinstance(code, str) or not isinstance(verifier, str):
            self._finish(ERROR_FAILED)
            return
        try:
            tokens = await self._token_request(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": f"{self._issuer}/deviceauth/callback",
                    "client_id": CLIENT_ID,
                    "code_verifier": verifier,
                }
            )
            async with self._file_lock():
                await self._save(tokens, None)
        except ProviderError as exc:
            logger.warning("chatgpt_login_failed code=%s reason=%s", exc.code, exc.reason)
            self._finish(ERROR_FAILED)
            return
        self._finish(None)

    async def status(self) -> dict[str, Any]:
        """What the portal shows. Never carries a token; ``account`` is the email, else the account id."""
        account = await self._read_account()
        pending = self._pending
        if account is not None:
            state = "connected"
        elif pending is not None:
            state = "pending"
        else:
            state = "disconnected"
        return {
            "state": state,
            "account": (account.email or account.account_id) if account is not None else None,
            "plan": account.plan if account is not None else None,
            "pending": (
                {
                    "user_code": pending.user_code,
                    "verification_url": pending.verification_url,
                    "expires_at": pending.expires_at,
                    "interval_s": pending.interval_s,
                    "slow_down": pending.slow_down,
                }
                if pending is not None and account is None
                else None
            ),
            "error": self._last_error if account is None else None,
        }

    async def disconnect(self) -> None:
        self._pending = None
        self._last_error = None
        async with self._file_lock():
            await self._clear()

    # --- tokens for calls ------------------------------------------------------------------------------

    @asynccontextmanager
    async def _file_lock(self) -> AsyncIterator[None]:
        """Exclusive lock shared with the other native process that reads these records."""

        def open_lock() -> int:
            self._lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            return os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)

        try:
            fd = await asyncio.to_thread(open_lock)
        except OSError:
            raise ProviderError("secret_unavailable", reason="login_lock") from None
        try:
            deadline = asyncio.get_running_loop().time() + LOCK_TIMEOUT_S
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if asyncio.get_running_loop().time() > deadline:
                        raise ProviderError("provider_timeout", reason="login_lock") from None
                    await asyncio.sleep(LOCK_POLL_S)
            yield
        finally:
            os.close(fd)  # closing the descriptor releases the lock

    def _fresh(self, access: _Access | None, stale: str | None) -> bool:
        return access is not None and access.token != stale and access.expires_at - SKEW_S > self._clock()

    async def credentials(self) -> ChatGptCredentials:
        """A token good for the next call; refreshed here when it is about to run out."""
        account = await self._read_account()
        if account is None:
            raise login_required()
        access = await self._read_access()
        if access is not None and self._fresh(access, None):
            return ChatGptCredentials(access.token, account.account_id)
        return await self._renew(access.token if access is not None else None)

    async def renew(self) -> ChatGptCredentials:
        """A new token after the API refused the current one (it can lapse before its own expiry says)."""
        account = await self._read_account()
        if account is None:
            raise login_required()
        access = await self._read_access()
        return await self._renew(access.token if access is not None else None)

    async def _renew(self, stale: str | None) -> ChatGptCredentials:
        """One refresh at a time, here and in the other native process; late callers use the winner's token."""
        async with self._refresh_lock, self._file_lock():
            account = await self._read_account()
            if account is None:
                raise login_required()
            access = await self._read_access()
            if self._fresh(access, stale):
                assert access is not None
                return ChatGptCredentials(access.token, account.account_id)
            try:
                tokens = await self._token_request(
                    {"grant_type": "refresh_token", "refresh_token": account.refresh_token, "client_id": CLIENT_ID}
                )
            except ProviderError as exc:
                if exc.reason == "login_required":
                    await self._clear()
                    self._last_error = ERROR_SESSION_EXPIRED
                raise
            account, access = await self._save(tokens, account)
            return ChatGptCredentials(access.token, account.account_id)
