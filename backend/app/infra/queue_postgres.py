"""PostgreSQL at-least-once deliveries with durable parking and fenced leases."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import timedelta
from typing import Any
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database import create_engine, create_session_factory
from app.infra.models import JobMessage
from app.infra.queue import DeferDelivery, JobQueue
from app.infra.queue_rabbitmq import _read_defer_delay, _read_max_retries, _read_retry_delay

logger = logging.getLogger(__name__)
VISIBILITY_SECONDS = 1800.0
POLL_SECONDS = 2.0
_CHANNEL = "sauri_jobs"


class PostgresJobQueue(JobQueue):
    """One sequential delivery per subscription; database transactions never span handlers."""

    def __init__(self, database_url: str | None = None) -> None:
        self._engine = create_engine(database_url)
        self._factory = create_session_factory(self._engine)
        self._listener: Any = None
        self._listener_lock = asyncio.Lock()
        self._consumers: set[asyncio.Task[None]] = set()
        self._in_flight: set[asyncio.Task[None]] = set()
        self._wakeups: set[asyncio.Event] = set()
        self._connected = False
        self._stopping = False

    def _require_connection(self) -> None:
        if not self._connected:
            raise RuntimeError("No active connection. Call `connect()` first.")

    def _wake(self, *_args: Any) -> None:
        for event in self._wakeups:
            event.set()

    async def _ensure_listener(self) -> None:
        async with self._listener_lock:
            if self._listener is not None and not self._listener.is_closed():
                return
            try:
                url = self._engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
                self._listener = await asyncpg.connect(url, timeout=POLL_SECONDS)
                await self._listener.add_listener(_CHANNEL, self._wake)
            except Exception:
                if self._listener is not None:
                    await self._listener.close()
                self._listener = None
                # Connection errors can contain credentials; never log the exception or DSN.
                logger.warning("Job notification connection unavailable; polling instead")

    async def connect(self) -> None:
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await self._ensure_listener()
        self._connected = True
        self._stopping = False

    async def disconnect(self) -> None:
        await self.stop_consuming()
        await self.cancel_in_flight()
        if self._listener is not None:
            await self._listener.close()
            self._listener = None
        await self._engine.dispose()
        self._connected = False

    async def _notify(self, session: AsyncSession) -> None:
        # PostgreSQL sends this only after the transaction commits; no payload is exposed.
        await session.execute(text("NOTIFY sauri_jobs"))

    async def publish(self, topic: str, message: dict[str, Any]) -> None:
        self._require_connection()
        async with self._factory() as session, session.begin():
            session.add(JobMessage(id=str(uuid4()), topic=topic, body=message))
            await self._notify(session)

    async def pending_count(self, topic: str) -> int | None:
        if not self._connected:
            return None
        try:
            async with self._factory() as session:
                return await session.scalar(select(func.count()).select_from(JobMessage).where(
                    JobMessage.topic == topic, *self._ready(),
                ))
        except Exception:
            return None

    @staticmethod
    def _ready() -> tuple[Any, Any]:
        # Parked deliveries are not ready, just like RabbitMQ's retry/defer queues.
        return (
            JobMessage.available_at <= func.now(),
            or_(JobMessage.locked_until.is_(None), JobMessage.locked_until <= func.now()),
        )

    async def _claim(self, topic: str) -> JobMessage | None:
        async with self._factory() as session, session.begin():
            message = await session.scalar(
                select(JobMessage).where(JobMessage.topic == topic, *self._ready())
                .order_by(JobMessage.available_at, JobMessage.created_at, JobMessage.id)
                .with_for_update(skip_locked=True).limit(1)
            )
            if message is not None:
                message.locked_until = await session.scalar(select(func.now() + timedelta(seconds=VISIBILITY_SECONDS)))
                await session.flush()
            return message

    async def _settle(self, delivery: JobMessage, outcome: str, delay: float = 0.0) -> None:
        async with self._factory() as session, session.begin():
            message = await session.scalar(select(JobMessage).where(
                JobMessage.id == delivery.id,
                JobMessage.locked_until == delivery.locked_until,
                JobMessage.locked_until > func.now(),
            ).with_for_update())
            if message is None:
                return  # An expired/stale handler cannot delete or retry a new owner's delivery.
            if outcome in {"ack", "failed"}:
                if outcome == "failed" and message.topic in {"transcribe", "summarize"}:
                    session.add(JobMessage(id=str(uuid4()), topic=f"{message.topic}.failed", body=message.body))
                await session.delete(message)
            else:
                if outcome == "retry":
                    message.attempts += 1
                    message.headers = {**message.headers, "x-sauri-retries": message.attempts}
                message.available_at = (await session.execute(
                    select(func.now() + timedelta(seconds=delay))
                )).scalar_one()
                message.locked_until = None
            await self._notify(session)

    async def _deliver(
        self, delivery: JobMessage, handler: Callable[[dict[str, Any]], Awaitable[None]],
        max_retries: int, retry_delay: float, defer_delay: float,
    ) -> None:
        try:
            outcome, delay = "ack", 0.0
            try:
                await handler(delivery.body)
            except DeferDelivery:
                outcome, delay = "defer", defer_delay
            except Exception:
                if delivery.attempts < max_retries:
                    outcome, delay = "retry", retry_delay
                elif delivery.topic in {"transcribe.failed", "summarize.failed"}:
                    # Terminal events must survive even if their consumer's database is down.
                    outcome = "release"
                else:
                    outcome = "failed"
            await self._settle(delivery, outcome, delay)
        except asyncio.CancelledError:
            with suppress(Exception):
                await self._settle(delivery, "release")
            raise

    async def subscribe(self, topic: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self._require_connection()
        if self._stopping:
            raise RuntimeError("Queue is stopping")
        wake = asyncio.Event()
        self._wakeups.add(wake)
        max_retries, retry_delay, defer_delay = _read_max_retries(topic), _read_retry_delay(topic), _read_defer_delay()

        async def consume() -> None:
            try:
                while not self._stopping:
                    wake.clear()
                    try:
                        await self._ensure_listener()
                        if self._stopping:
                            break
                        # Start the local deadline before the DB lease: cancel a slow handler before
                        # another consumer can reclaim it. Settlement is fenced independently.
                        async with asyncio.timeout(VISIBILITY_SECONDS):
                            claim = asyncio.create_task(self._claim(topic))
                            try:
                                delivery = await asyncio.shield(claim)
                            except asyncio.CancelledError:
                                # A shutdown racing COMMIT must release the resulting lease too.
                                with suppress(Exception):
                                    delivery = await claim
                                    if delivery is not None:
                                        await self._settle(delivery, "release")
                                raise
                            if delivery is not None:
                                if self._stopping:
                                    await self._settle(delivery, "release")
                                    break
                                consumer = asyncio.current_task()
                                assert consumer is not None
                                self._in_flight.add(consumer)
                                try:
                                    await self._deliver(delivery, handler, max_retries, retry_delay, defer_delay)
                                finally:
                                    self._in_flight.discard(consumer)
                                continue
                    except Exception:
                        logger.warning("Job queue operation failed; delivery remains recoverable")
                    if not self._stopping:
                        with suppress(TimeoutError):
                            await asyncio.wait_for(wake.wait(), timeout=POLL_SECONDS)
            finally:
                self._wakeups.discard(wake)

        task = asyncio.create_task(consume())
        self._consumers.add(task)
        task.add_done_callback(self._consumers.discard)

    async def stop_consuming(self) -> None:
        self._stopping = True
        self._wake()

    async def wait_idle(self, timeout_s: float) -> bool:
        # Include any in-progress claim when draining, not only handlers already entered.
        tasks = self._consumers if self._stopping else self._in_flight
        if tasks:
            _, pending = await asyncio.wait(set(tasks), timeout=timeout_s)
            return not pending
        return True

    async def cancel_in_flight(self) -> None:
        tasks = list(self._consumers)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
