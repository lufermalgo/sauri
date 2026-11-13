"""Synthetic-only state transitions at the processing-worker boundary, in an isolated E2E DB.

No AUTH_DISABLED, fake HTTP response, production data, or service override is used.
"""
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone

import boto3
from sqlalchemy import select

from app.auth.passwords import hash_password
from app.infra.database import Base, create_engine, create_session_factory
from app.infra.models import Meeting, SessionRecording, Transcript, User
import app.infra.models  # noqa: F401 - register all production tables


def now():
    return datetime.now(timezone.utc)


async def main():
    run = os.environ.get("SAURI_E2E_RUN_ID", "")
    db = os.environ.get("DATABASE_URL", "")
    if not run.startswith("sauri-e2e-") or "/sauri_e2e" not in db or "127.0.0.1:" not in db:
        raise RuntimeError("Refusing fixture outside uniquely named isolated E2E database")
    operation = sys.argv[1]
    engine = create_engine()
    factory = create_session_factory(engine)
    try:
        if operation == "init":
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with factory() as session, session.begin():
                for label in ("owner", "other"):
                    session.add(User(
                        id=str(uuid.uuid4()), email=f"{label}@synthetic.invalid",
                        name=f"Synthetic {label}", password_hash=hash_password("synthetic-only-password"),
                        is_sales=True, created_at=now(),
                    ))
            client = boto3.client("s3", endpoint_url=os.environ["OBJECT_STORE_ENDPOINT"],
                aws_access_key_id=os.environ["MINIO_ROOT_USER"],
                aws_secret_access_key=os.environ["MINIO_ROOT_PASSWORD"])
            client.create_bucket(Bucket=os.environ["OBJECT_STORE_BUCKET"])
        elif operation in ("complete", "unavailable", "assets"):
            meeting_id = sys.argv[2]
            async with factory() as session, session.begin():
                meeting = await session.get(Meeting, meeting_id)
                recording = (await session.execute(select(SessionRecording).where(
                    SessionRecording.meeting_id == meeting_id))).scalar_one()
                assert meeting is not None and meeting.process_state == ("completed" if operation == "assets" else "transcribing")
                assert recording.video_presence == "muxed"
                meeting.process_state = "completed"
                if operation != "unavailable":
                    session.add(Transcript(id=str(uuid.uuid4()), meeting_id=meeting_id,
                        language="es", provider="synthetic-e2e", supports_turns=False, created_at=now()))
                print(json.dumps({"recording_id": recording.id, "meeting_id": meeting.id,
                                  "session_id": recording.idempotency_key, "audio_ref": recording.audio_ref}))
        elif operation == "failed":
            async with factory() as session, session.begin():
                meeting = await session.get(Meeting, sys.argv[2])
                assert meeting is not None and meeting.process_state == "transcribing"
                meeting.process_state = "failed"
                meeting.failure_cause = "engine_failure"
        else:
            raise ValueError(operation)
    finally:
        await engine.dispose()


asyncio.run(main())
