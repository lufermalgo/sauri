"""Database configuration and base model for SQLAlchemy 2.0."""

import os

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""

    pass


def get_database_url() -> str:
    """Get the database URL; the password may come from the file named by DATABASE_PASSWORD_FILE."""
    from app.infra.secrets import SecretUnavailableError, read_secret, require_url_password, with_password

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SecretUnavailableError("Set DATABASE_URL (the password goes in DATABASE_PASSWORD_FILE)")
    url = with_password(url, read_secret("DATABASE_PASSWORD_FILE"))
    require_url_password(url, "DATABASE_PASSWORD_FILE", "DATABASE_URL")
    return url


def create_engine(database_url: str | None = None) -> AsyncEngine:
    """Create an async SQLAlchemy engine."""
    url = database_url or get_database_url()
    return create_async_engine(url, echo=False)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to the given engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
