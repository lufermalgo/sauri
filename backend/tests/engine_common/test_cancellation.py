"""Engine work stops once nobody is waiting for it (#1166)."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from sauri_engine_common import cancellation


def test_outside_a_bound_job_nothing_is_ever_cancelled():
    assert not cancellation.cancelled()
    cancellation.checkpoint()


def test_checkpoint_raises_once_the_caller_left_and_unbinding_restores_the_previous_state():
    left = threading.Event()
    token = cancellation.bind(left)
    cancellation.checkpoint()
    left.set()
    with pytest.raises(cancellation.JobCancelled):
        cancellation.checkpoint()
    cancellation.unbind(token)
    cancellation.checkpoint()


def test_the_binding_reaches_a_worker_thread():
    left = threading.Event()
    left.set()
    token = cancellation.bind(left)
    try:
        outcome: list[bool] = []
        thread = threading.Thread(target=lambda: outcome.append(cancellation.cancelled()))
        # A plain thread starts with an empty context; the thread pool copies it, as asyncio.to_thread does.
        asyncio.run(asyncio.to_thread(lambda: outcome.append(cancellation.cancelled())))
        thread.start()
        thread.join()
        assert outcome == [True, False]
    finally:
        cancellation.unbind(token)


def test_acquire_takes_a_free_lock_and_times_out_on_a_held_one():
    lock = threading.Lock()
    assert cancellation.acquire(lock, 1)
    started = time.monotonic()
    assert not cancellation.acquire(lock, 0.3)
    assert time.monotonic() - started < 2
    lock.release()


def test_acquire_stops_waiting_when_the_caller_leaves():
    lock = threading.Lock()
    lock.acquire()
    left = threading.Event()
    token = cancellation.bind(left)
    try:
        threading.Timer(0.2, left.set).start()
        started = time.monotonic()
        with pytest.raises(cancellation.JobCancelled):
            cancellation.acquire(lock, 60)
        assert time.monotonic() - started < 3
    finally:
        cancellation.unbind(token)
        lock.release()


async def test_watcher_sets_the_event_when_the_client_disconnects():
    left = threading.Event()
    checks = iter([False, False, True])

    async def is_disconnected() -> bool:
        return next(checks)

    await asyncio.wait_for(cancellation.cancel_on_disconnect(is_disconnected, left, interval_s=0.01), 2)
    assert left.is_set()
