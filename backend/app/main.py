"""sauri backend – FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ingesta.router import router as ingesta_router
from app.reuniones.router import router as reuniones_router

app = FastAPI(
    title="sauri",
    description="Plataforma interna de inteligencia de reuniones comerciales de Summan",
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
app.include_router(ingesta_router)
app.include_router(reuniones_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health-check endpoint."""
    return {"status": "ok"}
