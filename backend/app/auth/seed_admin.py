"""Create the single administrator account at bring-up.

Usage: ``python -m app.auth.seed_admin [--reset-password] [--retire-legacy]``

The password is read only from the file named by ``SAURI_ADMIN_PASSWORD_FILE``
(default ``/run/secrets/sauri_admin_password``). It is never printed, logged
or returned. Output is limited to status words and counts.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import hash_password
from app.auth.seed import ADMIN_EMAIL, seed_users
from app.infra.database import create_engine, create_session_factory
from app.infra.models import (
    AccessLog,
    ManualRecoveryPilotGate,
    Meeting,
    MeetingRecoveryOperation,
    SummaryTemplate,
    TemplateCategory,
    User,
)

DEFAULT_PASSWORD_FILE = "/run/secrets/sauri_admin_password"
MIN_PASSWORD_LENGTH = 20
LEGACY_SEED_EMAILS = ("comercial1@summan.com", "comercial2@summan.com")

# Every column that references a user (with or without a foreign key).
_USER_REFERENCES = (
    ("meetings", Meeting.created_by),
    ("access_log", AccessLog.user_id),
    ("meeting_recovery_operations", MeetingRecoveryOperation.actor_id),
    ("manual_recovery_pilot_gate.authorized_by", ManualRecoveryPilotGate.authorized_by),
    ("manual_recovery_pilot_gate.verification_actor_id", ManualRecoveryPilotGate.verification_actor_id),
    ("template_categories", TemplateCategory.owner_user_id),
    ("summary_templates", SummaryTemplate.owner_user_id),
)


class AdminPasswordError(Exception):
    """The admin password file is unusable. Messages never contain the value."""


def read_admin_password() -> str:
    path = Path(os.environ.get("SAURI_ADMIN_PASSWORD_FILE", DEFAULT_PASSWORD_FILE))
    try:
        password = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as error:
        raise AdminPasswordError(f"Admin password file not found: {path}") from error
    except OSError as error:
        raise AdminPasswordError(f"Admin password file is not readable: {path}") from error
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AdminPasswordError(
            f"Admin password file must contain at least {MIN_PASSWORD_LENGTH} characters: {path}"
        )
    return password


async def ensure_admin(session: AsyncSession, password: str, *, reset_password: bool) -> tuple[User, str]:
    """Creates the admin if missing; an existing admin keeps its password unless reset."""
    created = await seed_users(session, password)
    if created:
        return created[0], "created"
    admin = (await session.execute(select(User).where(User.email == ADMIN_EMAIL))).scalar_one()
    if reset_password:
        admin.password_hash = hash_password(password)
        admin.token_version += 1  # A reset signs the account out everywhere.
        await session.flush()
        return admin, "password reset"
    return admin, "unchanged"


async def retire_legacy_users(session: AsyncSession, admin: User) -> dict[str, int]:
    """Reassigns everything the legacy seed users own to the admin, then deletes them."""
    legacy = (await session.execute(select(User).where(User.email.in_(LEGACY_SEED_EMAILS)))).scalars().all()
    if not legacy:
        return {"legacy_users_deleted": 0}
    legacy_ids = [user.id for user in legacy]
    counts: dict[str, int] = {}
    for label, column in _USER_REFERENCES:
        result = await session.execute(
            update(column.class_).where(column.in_(legacy_ids)).values({column.key: admin.id})
        )
        counts[label] = int(result.rowcount)  # type: ignore[attr-defined]
    if admin.default_summary_template_id is None:
        admin.default_summary_template_id = next(
            (user.default_summary_template_id for user in legacy if user.default_summary_template_id), None
        )
    result = await session.execute(delete(User).where(User.id.in_(legacy_ids)))
    counts["legacy_users_deleted"] = int(result.rowcount)  # type: ignore[attr-defined]
    return counts


async def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.auth.seed_admin")
    parser.add_argument("--reset-password", action="store_true", help="replace an existing admin password")
    parser.add_argument("--retire-legacy", action="store_true", help="move legacy seed users' data to the admin")
    args = parser.parse_args(argv)
    try:
        password = read_admin_password()
    except AdminPasswordError as error:
        print(str(error), file=sys.stderr)
        return 2

    engine = create_engine()
    try:
        async with create_session_factory(engine)() as session, session.begin():
            admin, status = await ensure_admin(session, password, reset_password=args.reset_password)
            counts = await retire_legacy_users(session, admin) if args.retire_legacy else None
    finally:
        await engine.dispose()

    print(f"Administrator account: {status}")
    if counts is not None:
        print("Legacy accounts retired: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    return 0


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
