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
    """Get database URL from environment variable."""
    return os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/sauri",
    )


def create_engine(database_url: str | None = None) -> AsyncEngine:
    """Create an async SQLAlchemy engine."""
    url = database_url or get_database_url()
    return create_async_engine(url, echo=False)


def crear_engine(database_url: str) -> AsyncEngine:
    """Crear un motor async SQLAlchemy (interfaz en español del dominio)."""
    return create_async_engine(database_url, echo=False)


def crear_session(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Crear una fábrica de sesiones async ligada al motor dado."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to the given engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
