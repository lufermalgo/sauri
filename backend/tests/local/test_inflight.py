"""The status API and deploy guard share the same real SQL and retain fail-closed behavior."""

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import Diarization, Meeting, MeetingProcessingClaim, SummaryRequestOutbox
from app.local.inflight import DEPLOY_GUARD_QUERY, INFLIGHT_QUERY, count_processing

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("kind", "state", "busy"),
    [
        ("meeting", "recording", True),
        ("meeting", "transcribing", True),
        ("meeting", "completed", False),
        ("meeting", "failed", False),
        ("speakers", "pending", True),
        ("speakers", "in_progress", True),
        ("speakers", "completed", False),
        ("speakers", "failed", False),
        ("summary", "pending", True),
        ("summary", "running", True),
        ("summary", "completed", False),
        ("summary", "failed", False),
        ("claim", "transcription", True),
        ("claim", "diarization", True),
        ("claim", "expired", False),
        ("claim", "summary", False),
    ],
)
async def test_all_guard_predicates(db_session: AsyncSession, kind: str, state: str, busy: bool) -> None:
    now = datetime.now(UTC)
    db_session.add(
        Meeting(
            id="meeting-id",
            origin="manual",
            process_state=state if kind == "meeting" else "completed",
            created_by="owner",
            created_at=now,
        )
    )
    await db_session.flush()
    if kind == "speakers":
        db_session.add(
            Diarization(
                id="diar-id",
                meeting_id="meeting-id",
                transcript_id="transcript-id",
                diarization_state=state,
                created_at=now,
                updated_at=now,
            )
        )
    elif kind == "summary":
        db_session.add(
            SummaryRequestOutbox(
                event_id="event-id",
                meeting_id="meeting-id",
                transcript_id="transcript-id",
                status=state,
                generation=1,
                template_id="template-id",
                template_version=1,
                instructions_snapshot="Synthetic",
                requested_at=now,
            )
        )
    elif kind == "claim":
        db_session.add(
            MeetingProcessingClaim(
                meeting_id="meeting-id",
                claim_kind="transcription" if state == "expired" else state,
                claim_expires_at=now + timedelta(hours=-1 if state == "expired" else 1),
            )
        )
    await db_session.flush()
    assert await count_processing(db_session) == int(busy)
    rows = (await db_session.execute(text(INFLIGHT_QUERY))).all()
    assert bool(rows) is busy
    if busy:
        # Two live signals for one meeting must not inflate the shutdown prompt's count.
        await db_session.execute(text("UPDATE meetings SET process_state = 'transcribing'"))
        assert await count_processing(db_session) == 1


@pytest.mark.parametrize(
    ("rows", "query_exit", "expected"), [("", "0", 0), ("meeting synthetic pending", "0", 1), ("", "1", 1)]
)
def test_deploy_guard_calls_shared_query_and_stays_fail_closed(
    tmp_path: Path,
    rows: str,
    query_exit: str,
    expected: int,
) -> None:
    docker = tmp_path / "docker"
    docker.write_text("""#!/usr/bin/env bash
case "$*" in
  "compose ps --status running --quiet postgres") echo synthetic-container ;;
  "compose exec -T postgres psql"*)
    printf '%s' "${@: -1}" > "$SQL_CAPTURE"
    printf '%s' "$SQL_ROWS"
    exit "$SQL_EXIT" ;;
esac
""")
    docker.chmod(0o700)
    capture = tmp_path / "query.sql"
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/platform/deploy-guard.sh"), "synthetic test"],
        env={
            "HOME": str(tmp_path),
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "SQL_CAPTURE": str(capture),
            "SQL_ROWS": rows,
            "SQL_EXIT": query_exit,
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == expected, result.stderr
    assert capture.read_text() == DEPLOY_GUARD_QUERY
