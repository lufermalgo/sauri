"""sauri backend – FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.auth.local import local_mode
from app.auth.router import router as auth_router
from app.engines.local_router import router as local_engines_router
from app.engines.router import router as engines_router
from app.infra.database import create_engine, create_session_factory
from app.infra.http_errors import request_validation_exception_handler, unhandled_exception_handler
from app.infra.http_security import LocalGuardMiddleware, SecurityHeadersMiddleware, cors_options, docs_paths
from app.infra.queue import create_job_queue
from app.infra.secrets import log_secret_sources
from app.ingestion.router import router as ingestion_router
from app.local.router import router as local_router
from app.media.router import router as media_router
from app.meetings.router import router as meetings_router
from app.portal.static import mount_portal
from app.regeneration.router import router as regeneration_router
from app.summaries.outbox import recover_outbox
from app.summaries.router import router as summaries_router
from app.templates.router import router as templates_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Recover pending summary deliveries while serving requests."""
    log_secret_sources(logger)
    engine = create_engine()
    queue = create_job_queue()
    try:
        async with recover_outbox(create_session_factory(engine), queue):
            yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    """Build the application; CORS, docs exposure and error handling come from the environment."""
    docs_url, redoc_url, openapi_url = docs_paths()
    application = FastAPI(
        title="Sauri",
        description="Summan's internal commercial-meeting intelligence platform",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )

    # Browser calls are limited to the configured origins (portal dev server, extension); see
    # app.infra.http_security. The last middleware added is the outermost, so the security headers
    # also cover preflight answers produced by the CORS layer.
    application.add_middleware(CORSMiddleware, **cors_options())
    if local_mode():
        application.add_middleware(LocalGuardMiddleware)
    application.add_middleware(SecurityHeadersMiddleware)

    application.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    application.add_exception_handler(Exception, unhandled_exception_handler)

    application.include_router(media_router)
    application.include_router(ingestion_router)
    application.include_router(meetings_router)
    application.include_router(regeneration_router)
    application.include_router(auth_router)
    application.include_router(local_router)
    application.include_router(templates_router)
    application.include_router(summaries_router)
    application.include_router(engines_router)
    application.include_router(local_engines_router)

    @application.get("/health")
    async def health() -> dict[str, str]:
        """Health-check endpoint."""
        return {"status": "ok"}

    mount_portal(application)

    return application


app = create_app()
