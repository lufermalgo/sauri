"""Stop engine work nobody is waiting for any more (#1166).

FastAPI does not cancel a handler when its client (the worker) times out or disconnects, and the
engines run the heavy work in a thread. The handler binds a ``threading.Event`` for the job and sets it
when the client goes away; the thread checks it between its steps (``checkpoint``) and while it waits for
the single job slot (``acquire``), so the remaining chunks are never started and the engine is free for
the next job. The binding is a context variable: the thread pool copies the context into the thread.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token

POLL_S = 0.5

_current: ContextVar[threading.Event | None] = ContextVar("engine_job_cancelled", default=None)


class JobCancelled(Exception):  # noqa: N818 - a control signal, not an error
    """The caller left; the job stops at its next checkpoint."""


def bind(event: threading.Event) -> Token[threading.Event | None]:
    return _current.set(event)


def unbind(token: Token[threading.Event | None]) -> None:
    _current.reset(token)


def cancelled() -> bool:
    event = _current.get()
    return event is not None and event.is_set()


def checkpoint() -> None:
    """Raise ``JobCancelled`` when the caller already left. A no-op outside a bound job."""
    if cancelled():
        raise JobCancelled


def acquire(lock: threading.Lock, timeout_s: float) -> bool:
    """``lock.acquire(timeout=timeout_s)`` that gives up early (raising ``JobCancelled``) if the caller leaves."""
    waited = 0.0
    while True:
        checkpoint()
        step = min(POLL_S, timeout_s - waited)
        if step <= 0:
            return False
        if lock.acquire(timeout=step):
            return True
        waited += step


async def cancel_on_disconnect(
    is_disconnected: Callable[[], Awaitable[bool]], event: threading.Event, interval_s: float = POLL_S,
) -> None:
    """Set ``event`` once the HTTP client has gone away (runs until then, or until cancelled)."""
    while not event.is_set():
        if await is_disconnected():
            event.set()
            return
        await asyncio.sleep(interval_s)
