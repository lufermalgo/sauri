"""On-demand backfill: python -m app.thumbnails [--retry-unavailable] [--limit N].

Processes recordings without a thumbnail one at a time, newest first, and prints how many
ended in each outcome. Safe to repeat: finished recordings are not touched again.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from app.infra.database import create_engine, create_session_factory
from app.infra.object_store import create_object_store
from app.thumbnails.service import process_pending


async def _run(retry_unavailable: bool, limit: int | None) -> None:
    engine = create_engine()
    try:
        tally = await process_pending(
            create_session_factory(engine),
            create_object_store(),
            include_unavailable=retry_unavailable,
            limit=limit,
        )
    finally:
        await engine.dispose()
    summary = ", ".join(f"{name}={count}" for name, count in sorted(tally.items())) or "nothing pending"
    print(f"Thumbnail backfill finished: {summary}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate missing recording thumbnails.")
    parser.add_argument("--retry-unavailable", action="store_true", help="also retry recordings marked unavailable")
    parser.add_argument("--limit", type=int, default=None, help="stop after this many recordings")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    asyncio.run(_run(args.retry_unavailable, args.limit))


if __name__ == "__main__":
    main()
