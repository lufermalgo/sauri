"""Authorization and denial auditing."""

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.audit import record_access
from app.auth.dependencies import get_current_user
from app.auth.local import local_mode
from app.auth.schemas import AuthenticatedUser


def verify_authorization(user: AuthenticatedUser, resource: str, action: str) -> bool:
    """Checks whether the user is authorized for the action on the resource.

    Current policy: only users with is_sales=True have access.

    Args:
        user: Authenticated user.
        resource: Resource being accessed.
        action: Action being attempted.

    Returns:
        True if authorized, False if denied.
    """
    return user.is_sales


def require_sales(
    get_session: Callable[..., Any],
) -> Any:
    """Creates a FastAPI dependency that requires an authorized sales user.

    Args:
        get_session: Callable providing the SQLAlchemy AsyncSession (DB dependency).

    Returns:
        FastAPI dependency that returns AuthenticatedUser if authorized.
    """

    async def _dependency(
        request: Request,
        user: Annotated[AuthenticatedUser, Depends(get_current_user)],
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> AuthenticatedUser:
        resource = f"{request.method} {request.url.path}"

        if not local_mode() and not verify_authorization(user, resource, request.method):
            await record_access(
                session=session,
                user_id=user.id,
                resource=resource,
                result="denied",
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access restricted to authorized sales users",
            )

        return user

    return _dependency
