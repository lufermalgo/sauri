"""Keep a worker's claim alive while it works, and give it back when the work is interrupted.

A claim (``processing_claims``) is a lease. ``LeaseScope`` is created by the queue handler of one
delivery. The worker arms it once it holds the claim: from then on a concurrent task renews the
lease, so even a single engine call that takes many minutes keeps the claim, and ``guard`` aborts
that call if the lease is lost to another worker. If the delivery ends by an exception (including
the cancellation of a shutdown that ran out of grace), the claim is released so the redelivery can
take it immediately instead of waiting for the lease to lapse.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable
from contextlib import suppress
from types import TracebackType
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.processing_claims import (
    UNTRACKED_HOLDER,
    ProcessingKind,
    heartbeat_seconds,
    lease_seconds,
    release_worker_claim,
    renew_claim,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ClaimLost(Exception):  # noqa: N818 - a control signal, not an error
    """The lease ran out or another worker took the claim over: stop, it is no longer ours."""


class LeaseScope:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        lease_s: float | None = None,
        heartbeat_s: float | None = None,
    ) -> None:
        self._factory = session_factory
        self._lease_s = lease_s if lease_s is not None else lease_seconds()
        self._heartbeat_s = heartbeat_s if heartbeat_s is not None else heartbeat_seconds()
        self._lost = asyncio.Event()
        self._beat: asyncio.Task[None] | None = None
        self._claim: tuple[str, int, str, ProcessingKind, object] | None = None  # holder keeps its reservation

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    def arm(
        self, *, meeting_id: str, generation: object, holder: str, kind: ProcessingKind, operation_id: object = None,
    ) -> None:
        """Start renewing the claim just won. Untracked work has no claim row and nothing to renew."""
        if holder == UNTRACKED_HOLDER or not isinstance(generation, int):
            return
        self._claim = (meeting_id, generation, holder, kind, operation_id)
        self._beat = asyncio.create_task(self._heartbeat(meeting_id, generation, holder, kind))

    async def _heartbeat(self, meeting_id: str, generation: int, holder: str, kind: ProcessingKind) -> None:
        deadline = time.monotonic() + self._lease_s
        while True:
            await asyncio.sleep(self._heartbeat_s)
            try:
                renewed = await renew_claim(
                    self._factory, meeting_id=meeting_id, generation=generation, holder=holder, kind=kind,
                    lease_s=self._lease_s,
                )
            except Exception:
                logger.warning("Could not renew the processing lease; meeting_id=%s", meeting_id)
                renewed = None
            if renewed:
                deadline = time.monotonic() + self._lease_s
            elif renewed is False or time.monotonic() >= deadline:
                logger.warning("Processing lease lost; kind=%s meeting_id=%s", kind, meeting_id)
                self._lost.set()
                return

    async def guard(self, work: Awaitable[T]) -> T:
        """Run ``work``; raise ``ClaimLost`` (cancelling it) the moment the lease is lost."""
        task = asyncio.ensure_future(work)
        lost = asyncio.ensure_future(self._lost.wait())
        try:
            await asyncio.wait({task, lost}, return_when=asyncio.FIRST_COMPLETED)
            if not task.done():
                raise ClaimLost
            return task.result()
        finally:
            for pending in (task, lost):
                if not pending.done():
                    pending.cancel()
            await asyncio.gather(task, lost, return_exceptions=True)

    async def __aenter__(self) -> LeaseScope:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None,
    ) -> None:
        if self._beat is not None:
            self._beat.cancel()
            with suppress(asyncio.CancelledError):
                await self._beat
        if self._claim is None or exc_type is None or exc_type is ClaimLost or self._lost.is_set():
            return
        meeting_id, generation, holder, kind, operation_id = self._claim

        async def release() -> None:
            async with self._factory() as session, session.begin():
                await release_worker_claim(
                    session, meeting_id=meeting_id, generation=generation, holder=holder, kind=kind,
                    operation_id=operation_id,
                )

        try:
            # Shielded: a delivery being cancelled (shutdown, a closed channel) is cancelled again
            # while it cleans up, and the release must still reach the database.
            await asyncio.shield(asyncio.ensure_future(release()))
        except Exception:
            # The lease lapses on its own; the release only shortens the wait.
            logger.warning("Could not release the processing claim; meeting_id=%s", meeting_id)
