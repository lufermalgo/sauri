"""sauri backend – FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.infra.database import create_engine, create_session_factory
from app.infra.queue import create_job_queue
from app.ingestion.router import router as ingestion_router
from app.meetings.router import router as meetings_router
from app.meetings.speaker_excerpt_service import ExcerptKeyring
from app.summaries.outbox import recover_outbox
from app.summaries.router import router as summaries_router
from app.templates.router import router as templates_router


def validate_speaker_excerpt_keyring() -> None:
    """Fail closed before serving requests if excerpt keys are not configured."""
    ExcerptKeyring.from_environment()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Validate encryption key material before serving requests."""
    validate_speaker_excerpt_keyring()
    engine = create_engine()
    queue = create_job_queue()
    try:
        async with recover_outbox(create_session_factory(engine), queue):
            yield
    finally:
        await engine.dispose()


app = FastAPI(
    title="sauri",
    description="Summan's internal commercial-meeting intelligence platform",
    version="0.1.0",
    lifespan=lifespan,
)


# CORS for local development (extension → backend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(ingestion_router)
app.include_router(meetings_router)
app.include_router(auth_router)
app.include_router(templates_router)
app.include_router(summaries_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health-check endpoint."""
    return {"status": "ok"}
