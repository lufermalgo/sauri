"""Pydantic schemas for the authentication module."""

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


class AuthenticatedUser(BaseModel):
    """Represents an authenticated user extracted from the JWT token."""

    id: str  # UUID as string
    email: str
    name: str
    is_sales: bool


MAX_EMAIL_LENGTH = 254
MAX_PASSWORD_LENGTH = 256

# Strict address syntax (no display names, quotes, comments or IP literals). `email-validator` is not a
# dependency, and it rejects reserved domains such as the `.local` addresses the seeded accounts use.
_EMAIL_PATTERN = re.compile(
    r"^(?=.{3,254}$)[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}"
    r"@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)


def _check_email(value: str) -> str:
    if not _EMAIL_PATTERN.fullmatch(value):
        raise ValueError("not a valid email address")
    return value


class LoginRequest(BaseModel):
    """Login request (Req. 13.2): bounded fields, no unknown keys."""

    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, Field(min_length=3, max_length=MAX_EMAIL_LENGTH), AfterValidator(_check_email)]
    password: Annotated[str, Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)]
    # Only the Chrome extension asks for a refreshable session (#1123); the portal never sends this.
    client: Literal["extension"] | None = None


class LoginResponse(BaseModel):
    """Authentication_Service response with the User_Session (Req. 13.3).

    The refresh fields are present only for ``client="extension"``; they are omitted, not null, otherwise.
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str | None = None
    refresh_expires_in: int | None = None


MAX_REFRESH_TOKEN_LENGTH = 512


class RefreshRequest(BaseModel):
    """Refresh request: the opaque refresh token and nothing else."""

    model_config = ConfigDict(extra="forbid")

    refresh_token: Annotated[str, Field(min_length=1, max_length=MAX_REFRESH_TOKEN_LENGTH)]
