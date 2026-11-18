"""Fill a DISPOSABLE source (database + S3 bucket) with synthetic meetings for the migration rehearsal.

Refuses a database or S3 endpoint that is not on 127.0.0.1 or that uses one of the owner's ports
(5432, 9000, 9001, 5672, 8000). Nothing here is real data.

    cd backend && uv run python ../scripts/migrate-from-docker/rehearsal/seed_synthetic.py \
        --database-url "$URL" --s3-endpoint http://127.0.0.1:19000 --access-key-file F --secret-key-file F
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import random
import uuid
from datetime import UTC, datetime, timedelta

import boto3
from botocore.config import Config
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.seed import seed_users
from app.infra.models import (
    Diarization,
    Meeting,
    SessionRecording,
    Speaker,
    SpeechTurn,
    StateHistory,
    Transcript,
    User,
)
from app.templates.seed import ensure_default

WORDS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo",
         "lima", "mike", "november"]
OWNER_PORTS = {5432, 9000, 9001, 5672, 8000}


def guard(url: str, endpoint: str) -> None:
    parsed = make_url(url)
    if parsed.host not in {"127.0.0.1", "localhost"} or parsed.port in OWNER_PORTS or parsed.port is None:
        raise SystemExit("refusing: the rehearsal database must be a disposable one on a non-owner loopback port")
    if not endpoint.startswith("http://127.0.0.1:") or int(endpoint.rsplit(":", 1)[1]) in OWNER_PORTS:
        raise SystemExit("refusing: the rehearsal S3 endpoint must be a disposable one on a non-owner port")


def read(path: str) -> str:
    with open(path, encoding="utf-8") as source:
        return source.read().strip()


def put(client: object, bucket: str, key: str, body: bytes) -> None:
    client.put_object(Bucket=bucket, Key=key, Body=body)  # type: ignore[attr-defined]


async def seed(args: argparse.Namespace) -> None:
    rng = random.Random(1221)
    engine = create_async_engine(args.database_url)
    client = boto3.client(
        "s3", endpoint_url=args.s3_endpoint, aws_access_key_id=read(args.access_key_file),
        aws_secret_access_key=read(args.secret_key_file), config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )
    with contextlib.suppress(client.exceptions.BucketAlreadyOwnedByYou):
        client.create_bucket(Bucket=args.bucket)
    objects = 0
    now = datetime.now(UTC)
    async with async_sessionmaker(engine, class_=AsyncSession)() as session, session.begin():
        if args.inflight:
            admin_id = await session.scalar(select(User.id).where(User.email == "admin@sauri.local"))
            assert admin_id is not None
            session.add(Meeting(id=str(uuid.uuid4()), title="synthetic in-flight", origin="manual",
                                process_state="transcribing", created_by=admin_id, created_at=now))
            print("added one in-flight meeting")
            return
        (admin,) = await seed_users(session, os.urandom(16).hex())
        await ensure_default(session, admin.id)
        other = User(id=str(uuid.uuid4()), email="second@sauri.local", name="Synthetic Second",
                     password_hash="!synthetic", is_sales=True, created_at=now)
        session.add(other)
        await session.flush()
        for index in range(args.meetings):
            meeting_id = str(uuid.uuid4())
            state = "failed" if index % 7 == 6 else "completed"
            created = now - timedelta(days=index)
            session.add(Meeting(id=meeting_id, title=f"Synthetic meeting {index}", origin="manual",
                                process_state=state, created_by=(admin if index % 3 else other).id,
                                created_at=created, recorded_at=created, recorded_at_source="capture"))
            await session.flush()
            for step, name in enumerate(("queued", "recording", "transcribing", state)):
                session.add(StateHistory(id=str(uuid.uuid4()), meeting_id=meeting_id, state=name,
                                         occurred_at=created + timedelta(minutes=step)))
            recording_id = str(uuid.uuid4())
            audio_key = f"recordings/{meeting_id}/{uuid.uuid4()}/audio"
            video_key = f"recordings/{meeting_id}/{uuid.uuid4()}/video"
            thumb_key = f"recordings/{meeting_id}/{recording_id}/thumbnail.jpg"
            # One large video exercises streaming; the rest stay small.
            video_size = 12 * 1024 * 1024 + 7 if index == 0 else rng.randint(20_000, 300_000)
            put(client, args.bucket, audio_key, b"\x1aE\xdf\xa3" + rng.randbytes(rng.randint(10_000, 200_000)))
            put(client, args.bucket, video_key, b"\x1aE\xdf\xa3" + rng.randbytes(video_size))
            put(client, args.bucket, thumb_key, b"\xff\xd8\xff" + rng.randbytes(rng.randint(2_000, 9_000)))
            objects += 3
            session.add(SessionRecording(
                id=recording_id, meeting_id=meeting_id, idempotency_key=str(uuid.uuid4()),
                capture_origin="chrome_extension", audio_ref=audio_key, video_ref=video_key,
                duration_seconds=rng.randint(60, 3600), finished_at=created, video_presence="present",
                thumbnail_ref=thumb_key, thumbnail_state="ready",
            ))
            if state != "completed":
                continue
            transcript_id = str(uuid.uuid4())
            session.add(Transcript(id=transcript_id, meeting_id=meeting_id, provider="synthetic",
                                   supports_turns=True, created_at=created))
            await session.flush()
            for turn in range(rng.randint(5, 30)):
                text = " ".join(rng.choice(WORDS) for _ in range(rng.randint(4, 20)))
                session.add(SpeechTurn(id=str(uuid.uuid4()), transcript_id=transcript_id, text=text,
                                       start_ms=turn * 4000, end_ms=turn * 4000 + 3500, sequence=turn + 1))
            diarization_id = str(uuid.uuid4())
            session.add(Diarization(id=diarization_id, meeting_id=meeting_id, transcript_id=transcript_id,
                                    provider="synthetic", speaker_count=2, diarization_state="completed",
                                    created_at=created, updated_at=created))
            await session.flush()
            for sequence in (1, 2):
                session.add(Speaker(id=str(uuid.uuid4()), diarization_id=diarization_id,
                                    raw_label=f"SPEAKER_{sequence:02d}", label=f"Speaker {sequence}",
                                    sequence=sequence))
    # Objects with no row (an orphan the app would sweep) still move: the copy is of the whole bucket.
    while objects < args.objects:
        put(client, args.bucket, f"recordings/{uuid.uuid4()}/{uuid.uuid4()}/audio", rng.randbytes(1_000))
        objects += 1
    await engine.dispose()
    print(f"seeded {args.meetings} meetings and {objects} objects")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--s3-endpoint", required=True)
    parser.add_argument("--bucket", default="sauri-recordings")
    parser.add_argument("--access-key-file", required=True)
    parser.add_argument("--secret-key-file", required=True)
    parser.add_argument("--meetings", type=int, default=14)
    parser.add_argument("--objects", type=int, default=50)
    parser.add_argument("--inflight", action="store_true", help="only add one meeting still being processed")
    args = parser.parse_args()
    guard(args.database_url, args.s3_endpoint)
    asyncio.run(seed(args))


if __name__ == "__main__":
    main()
