"""sauri async worker entrypoint.

Runnable as: python -m app.worker

Connects the job queue, starts the transcription worker and keeps the
loop running until interrupted (SIGINT/SIGTERM).
"""

from __future__ import annotations

import asyncio
import logging
import signal

from app.diarization.worker import start_worker as start_diarization_worker
from app.infra.database import create_engine, create_session_factory
from app.infra.object_store import create_object_store
from app.infra.queue import create_job_queue
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


async def main() -> None:
    """Starts the queue, subscribes workers, and waits until shutdown."""
    logger.info("Starting sauri worker...")

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

    # Wait for shutdown signal
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received, closing...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await stop_event.wait()

    # Cleanup
    retention_task.cancel()
    thumbnail_task.cancel()
    stale_summary_task.cancel()
    await queue.disconnect()
    await engine.dispose()
    logger.info("sauri worker finished")


if __name__ == "__main__":
    asyncio.run(main())
