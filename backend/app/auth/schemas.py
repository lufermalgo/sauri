"""Pydantic schemas for the authentication module."""

from pydantic import BaseModel


class AuthenticatedUser(BaseModel):
    """Represents an authenticated user extracted from the JWT token."""

    id: str  # UUID as string
    email: str
    name: str
    is_sales: bool


class LoginRequest(BaseModel):
    """Login request (Req. 13.2)."""

    email: str
    password: str


class LoginResponse(BaseModel):
    """Authentication_Service response with the User_Session (Req. 13.3)."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
