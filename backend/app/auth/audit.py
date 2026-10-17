"""Access audit — records allowed and denied attempts."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import AccessLog


async def record_access(
    session: AsyncSession,
    user_id: str | None,
    resource: str,
    result: str,
) -> None:
    """Creates an AccessLog entry in the database.

    Args:
        session: Async SQLAlchemy session.
        user_id: UUID of the requesting user (None if unauthenticated).
        resource: Resource the access attempt targeted.
        result: "allowed" or "denied".
    """
    entry = AccessLog(
        id=str(uuid4()),
        user_id=user_id,
        resource=resource,
        result=result,
        occurred_at=datetime.now(UTC),
    )
    session.add(entry)
    await session.commit()
