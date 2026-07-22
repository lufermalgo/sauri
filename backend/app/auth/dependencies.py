"""FastAPI dependencies for JWT authentication."""

import os

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.auth.schemas import AuthenticatedUser
from app.auth.token import JWT_ALGORITHM, JWT_SECRET

_bearer_scheme = HTTPBearer(auto_error=False)

_DEV_USER = AuthenticatedUser(
    id="dev-user-00000000",
    email="dev@sauri.local",
    name="Developer (auth disabled)",
    is_sales=True,
)


def _bypass_active() -> bool:
    """Determines whether the AUTH_DISABLED bypass is active.

    Restricted to the test environment (Req. 13.1, 13.4): with the
    addition of `POST /api/v1/auth/login` (chrome-side-panel), the
    development bypass is retired outside automated tests; endpoints
    require a real JWT issued by the Authentication_Service. It's kept
    only for test (`APP_ENV=test`) where other modules still use it as
    a shortcut.
    """
    auth_disabled = os.getenv("AUTH_DISABLED", "").lower() in ("1", "true", "yes")
    app_env = os.getenv("APP_ENV", "").lower()
    return auth_disabled and app_env == "test"


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthenticatedUser:
    """Extracts and validates the JWT token from the Authorization header.

    Returns:
        AuthenticatedUser with the token's data.

    Raises:
        HTTPException 401: if the token is missing, invalid, or expired.
    """
    # Bypass only in the test environment (AUTH_DISABLED=1 and APP_ENV=test), Req. 13.1, 13.4
    if _bypass_active():
        return _DEV_USER

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    sub: str | None = payload.get("sub")
    email: str | None = payload.get("email")
    name: str | None = payload.get("name")
    is_sales: bool | None = payload.get("is_sales")

    if sub is None or email is None or name is None or is_sales is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token with incomplete claims",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return AuthenticatedUser(
        id=sub,
        email=email,
        name=name,
        is_sales=is_sales,
    )
