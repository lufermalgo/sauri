"""Authentication_Service — POST /api/v1/auth/login (chrome-side-panel, Req. 13).

Validates the Sales_User's credentials against the minimal `User` store
and issues the User_Session (JWT) with `create_token`.
Not an integration with Summan's IdP.

Requirements: 13.2, 13.3, 13.5
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.auth.passwords import verify_password
from app.auth.schemas import LoginRequest, LoginResponse
from app.auth.token import create_token
from app.infra.database import create_engine, create_session_factory
from app.infra.models import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_EXPIRES_MINUTES = 60


@router.post("/login", response_model=LoginResponse)
async def login(login_request: LoginRequest) -> LoginResponse:
    """Validates credentials and issues a JWT (Req. 13.2, 13.3).

    401 if the email doesn't exist or the password is wrong — the response
    doesn't distinguish between the two cases so it doesn't leak which
    emails exist.
    """
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            stmt = select(User).where(User.email == login_request.email)
            user = (await session.execute(stmt)).scalar_one_or_none()

            if user is None or not verify_password(login_request.password, user.password_hash):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials",
                )

            token = create_token(
                user_id=user.id,
                email=user.email,
                name=user.name,
                is_sales=user.is_sales,
                expires_minutes=_EXPIRES_MINUTES,
            )
            return LoginResponse(
                access_token=token,
                token_type="bearer",
                expires_in=_EXPIRES_MINUTES * 60,
            )
    finally:
        await engine.dispose()
