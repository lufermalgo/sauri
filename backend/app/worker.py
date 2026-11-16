"""sauri async worker entrypoint.

Runnable as: python -m app.worker

Connects the job queue, starts the transcription worker and keeps the
loop running until interrupted (SIGINT/SIGTERM).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from app.diarization.worker import start_worker as start_diarization_worker
from app.infra.database import create_engine, create_session_factory
from app.infra.object_store import create_object_store
from app.infra.orphan_sweeper import run_orphan_sweeper
from app.infra.queue import JobQueue, create_job_queue
from app.infra.secrets import log_secret_sources
from app.regeneration.sweeper import run_stale_operation_sweeper
from app.retention.worker import start_retention_worker
from app.summaries.sweeper import run_stale_request_sweeper
from app.summaries.worker import start_worker as start_summary_worker
from app.thumbnails.service import run_thumbnail_sweeper
from app.transcription.worker import start_worker as start_transcription_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# How long a stopping worker lets running jobs finish before it gives their claims back.
# docker-compose's stop_grace_period for the worker must stay above this.
DEFAULT_SHUTDOWN_GRACE_SECONDS = 540.0


def shutdown_grace_seconds() -> float:
    raw = os.environ.get("WORKER_SHUTDOWN_GRACE_SECONDS", "").strip()
    try:
        value = float(raw) if raw else DEFAULT_SHUTDOWN_GRACE_SECONDS
    except ValueError:
        value = -1.0
    if value < 0:
        logger.warning(
            "WORKER_SHUTDOWN_GRACE_SECONDS='%s' is not usable; using %g.", raw, DEFAULT_SHUTDOWN_GRACE_SECONDS,
        )
        return DEFAULT_SHUTDOWN_GRACE_SECONDS
    return value


async def stop_gracefully(queue: JobQueue, grace_s: float) -> bool:
    """Stop taking jobs, let running ones finish for ``grace_s``, then hand the rest back.

    A job that does not finish in time is cancelled: it releases its claim and its delivery goes
    back to the queue, so another worker (or this one after its restart) resumes it at once.
    Returns True when every job finished by itself.
    """
    await queue.stop_consuming()
    if await queue.wait_idle(grace_s):
        return True
    logger.warning("Grace period of %gs elapsed with jobs still running; releasing them", grace_s)
    await queue.cancel_in_flight()
    return False


async def main() -> None:
    """Starts the queue, subscribes workers, and waits until shutdown."""
    logger.info("Starting sauri worker...")
    log_secret_sources(logger)

    # Infrastructure
    engine = create_engine()
    session_factory = create_session_factory(engine)
    queue = create_job_queue()

    object_store = create_object_store()

    await queue.connect()
    logger.info("Queue connection established")

    # Subscribe transcription worker
    await start_transcription_worker(queue, session_factory)

    # Subscribe diarization worker (topic 'diarize', Req. 1.1)
    await start_diarization_worker(queue, session_factory)

    # T12 registers the consumer; absent T14 local engine configuration fails startup.
    await start_summary_worker(queue, session_factory)

    # Start retention worker as a background task
    retention_task = asyncio.create_task(
        start_retention_worker(session_factory, object_store)
    )

    # Library thumbnails: derived data, cut one recording at a time outside the transcription path.
    thumbnail_task = asyncio.create_task(run_thumbnail_sweeper(session_factory, object_store))

    # Requests whose broker message was lost would otherwise stay pending/running forever.
    stale_summary_task = asyncio.create_task(run_stale_request_sweeper(session_factory))

    # Explicit regeneration runs whose worker never reported back must release the meeting.
    stale_operation_task = asyncio.create_task(run_stale_operation_sweeper(session_factory))

    # Work a restart or crash left without a worker (and nothing left to redeliver) must not wait for ever.
    orphan_task = asyncio.create_task(run_orphan_sweeper(session_factory, queue))

    # Wait for shutdown signal
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received, closing...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await stop_event.wait()

    # Sweepers first: nothing may be republished while running jobs drain.
    for task in (orphan_task, stale_summary_task, stale_operation_task, retention_task, thumbnail_task):
        task.cancel()
    await stop_gracefully(queue, shutdown_grace_seconds())
    await queue.disconnect()
    await engine.dispose()
    logger.info("sauri worker finished")


if __name__ == "__main__":
    asyncio.run(main())
