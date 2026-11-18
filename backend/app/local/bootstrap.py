"""Create the real local owner and starter templates; print only the owner's id."""

import argparse
import asyncio
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database import create_engine, create_session_factory
from app.infra.models import User
from app.templates.seed import ensure_default

LOCAL_EMAIL = "local@sauri.local"


async def ensure_local_user(session: AsyncSession, name: str) -> User:
    name = name.strip()
    if not name or len(name) > 255:
        raise ValueError("local_user_name_invalid")
    user = await session.scalar(select(User).where(User.email == LOCAL_EMAIL))
    if user is None:
        user = User(
            id=str(uuid.uuid4()),
            email=LOCAL_EMAIL,
            name=name,
            password_hash="!local-account",
            is_sales=True,
            created_at=datetime.now(UTC),
        )
        session.add(user)
        await session.flush()
    await ensure_default(session, user.id)
    return user


async def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.local.bootstrap")
    parser.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    if not args.name.strip() or len(args.name.strip()) > 255:
        parser.error("name must contain 1 to 255 characters")
    engine = create_engine()
    try:
        async with create_session_factory(engine)() as session, session.begin():
            user = await ensure_local_user(session, args.name)
    finally:
        await engine.dispose()
    print(user.id)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
