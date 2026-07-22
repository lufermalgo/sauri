"""Utility for creating JWT tokens (development and testing)."""

import os
from datetime import datetime, timedelta, timezone

from jose import jwt

JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")


def create_token(
    user_id: str,
    email: str,
    name: str,
    is_sales: bool,
    expires_minutes: int = 60,
) -> str:
    """Creates a JWT token with the user's claims.

    Args:
        user_id: UUID of the user as a string.
        email: User's email.
        name: User's name.
        is_sales: Whether the user is an authorized sales user.
        expires_minutes: Minutes until the token expires.

    Returns:
        JWT token encoded as a string.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "name": name,
        "is_sales": is_sales,
        "exp": now + timedelta(minutes=expires_minutes),
        "iat": now,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
