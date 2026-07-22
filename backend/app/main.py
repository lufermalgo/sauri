"""sauri backend – FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.ingestion.router import router as ingestion_router
from app.reuniones.router import router as reuniones_router

app = FastAPI(
    title="sauri",
    description="Summan's internal commercial-meeting intelligence platform",
    version="0.1.0",
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
app.include_router(reuniones_router)
app.include_router(auth_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health-check endpoint."""
    return {"status": "ok"}
