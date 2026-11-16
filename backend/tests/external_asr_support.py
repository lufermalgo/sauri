"""Fakes shared by the U4.3 tests: an AssemblyAI-shaped provider and a loopback server helper.

Only the documented answer shapes are reproduced (upload, create, poll, delete). The audio is synthetic
(a tone) and the provider never decodes it. Nothing here speaks for the real provider: Spanish quality and
limits stay NO VERIFICADO until U10.
"""

from __future__ import annotations

import importlib.util
import math
import sys
import threading
import wave
from array import array
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.copy.engine_notices_es import NOTICE_VERSIONS
from app.infra.models import EnginePrivacyConsent, EngineProcessSetting, EngineProvider

Factory = async_sessionmaker[AsyncSession]
OWNER = "00000000-0000-4000-8000-00000000000a"

PROVIDER_KEY = "sk-synthetic-provider-key-0123456789"
PHRASE = "frase confidencial del proveedor"
RATE = 16000


def load_native_asr(name: str) -> ModuleType:
    """Import ``backend/asr-engine/native_main.py`` under ``name`` (as the gateway tests do)."""
    path = Path(__file__).resolve().parents[1] / "asr-engine" / "native_main.py"
    sys.path[:0] = [str(path.parent), str(path.parent.parent / "engine-common")]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_tone_wav(path: Path, seconds: float) -> int:
    """Write a PCM16 mono 16 kHz tone (what ``normalize_to_wav`` produces); return its duration in ms."""
    tone = array("h", (round(9000 * math.sin(2 * math.pi * 440 * i / RATE)) for i in range(RATE)))
    frames = round(seconds * RATE)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        data = array("h")
        while len(data) < frames:
            data.extend(tone)
        out.writeframes(data[:frames].tobytes())
    return round(frames * 1000 / RATE)


@dataclass
class Served:
    port: int
    server: uvicorn.Server

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


@contextmanager
def serve(app: FastAPI) -> Iterator[Served]:
    """Run ``app`` on a random free loopback port in a thread (never one of 8001-8005)."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, lifespan="off", log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(500):
        if server.started and server.servers:
            break
        threading.Event().wait(0.01)
    else:
        raise RuntimeError("test server did not start")
    port = server.servers[0].sockets[0].getsockname()[1]
    assert port not in range(8001, 8006)
    try:
        yield Served(port, server)
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@dataclass
class Seen:
    method: str
    path: str
    authorization: str | None


WordSpec = tuple[str, int, int]  # text, start_ms, end_ms on the part clock


@dataclass
class FakeAssemblyAI:
    """``words_for(n)`` answers the n-th created transcript (0-based); failures are switches."""

    words_for: Callable[[int], list[WordSpec]] = field(default=lambda n: [("Hola", 100, 400), ("mundo.", 450, 900)])
    language: str = "es"
    upload_status: int = 200
    upload_headers: dict[str, str] = field(default_factory=dict)
    create_status: int = 200
    processing_polls: int = 0  # polls answered "processing" before completing
    hang: bool = False  # never complete (cancellation tests)
    include_text: bool = True
    text: str | None = None  # overrides the text joined from the words
    padding_bytes: int = 0  # extra JSON the completed answer carries (response cap tests)
    seen: list[Seen] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    created: int = 0
    polls: dict[str, int] = field(default_factory=dict)

    def app(self) -> FastAPI:
        provider = FastAPI(docs_url=None, openapi_url=None)

        @provider.middleware("http")
        async def record(request: Request, call_next: Any) -> Response:
            self.seen.append(Seen(request.method, request.url.path, request.headers.get("authorization")))
            return await call_next(request)

        @provider.post("/v2/upload")
        async def upload(request: Request) -> Response:
            await request.body()
            if self.upload_status != 200:
                return JSONResponse({"error": "synthetic"}, status_code=self.upload_status, headers=self.upload_headers)
            return JSONResponse({"upload_url": "https://cdn.example.invalid/upload/abc"})

        @provider.post("/v2/transcript")
        async def create(request: Request) -> Response:
            await request.json()
            if self.create_status != 200:
                return JSONResponse({"error": "synthetic"}, status_code=self.create_status)
            identifier = f"job-{self.created}"
            self.created += 1
            return JSONResponse({"id": identifier, "status": "queued"})

        @provider.get("/v2/transcript/{identifier}")
        async def poll(identifier: str) -> Response:
            count = self.polls[identifier] = self.polls.get(identifier, 0) + 1
            if self.hang or count <= self.processing_polls:
                return JSONResponse({"id": identifier, "status": "processing"})
            index = int(identifier.split("-")[1])
            words = self.words_for(index)
            document: dict[str, Any] = {
                "id": identifier,
                "status": "completed",
                "text": self.text
                if self.text is not None
                else (" ".join(text for text, _s, _e in words) if self.include_text else ""),
                "language_code": self.language,
                "audio_duration": 3600,
                "words": [
                    {"text": text, "start": start, "end": end, "confidence": 0.9} for text, start, end in words
                ],
            }
            if self.padding_bytes:
                document["padding"] = "x" * self.padding_bytes
            return JSONResponse(document)

        @provider.delete("/v2/transcript/{identifier}")
        async def delete(identifier: str) -> Response:
            self.deleted.append(identifier)
            return JSONResponse({"id": identifier, "status": "completed", "text": None})

        return provider

    def calls(self, method: str, path_prefix: str) -> list[Seen]:
        return [s for s in self.seen if s.method == method and s.path.startswith(path_prefix)]


# --- rows the worker reads (provider, choice, consent) ---------------------------------------------------


async def add_provider(
    factory: Factory, owner: str = OWNER, kind: str = "assemblyai", *, enabled: bool = True,
    secret_ref: str | None = "sauri/owner/provider", base_url: str | None = "https://api.assemblyai.com",
) -> str:
    identifier = str(uuid4())
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        session.add(EngineProvider(
            id=identifier, owner_id=owner, kind=kind, label=f"{kind}-{identifier[:6]}", base_url=base_url,
            enabled=enabled, secret_ref=secret_ref, key_hint=None, key_set_at=None, created_at=now, updated_at=now,
        ))
    return identifier


async def choose(
    factory: Factory, provider_id: str | None, model: str = "universal-2", *, owner: str = OWNER,
    capability: str = "transcription", fallback: bool = True,
) -> None:
    async with factory() as session, session.begin():
        row = await session.get(EngineProcessSetting, (owner, capability))
        if row is None:
            row = EngineProcessSetting(
                owner_id=owner, capability=capability, provider_id=provider_id, model=model,
                local_fallback=fallback, version=1, updated_at=datetime.now(UTC),
            )
            session.add(row)
        else:
            row.provider_id, row.model, row.local_fallback = provider_id, model, fallback
            row.version += 1


async def consent(
    factory: Factory, provider_id: str, *, owner: str = OWNER, capability: str = "transcription",
    version: int | None = None, revoked: bool = False,
) -> None:
    async with factory() as session, session.begin():
        session.add(EnginePrivacyConsent(
            id=str(uuid4()), owner_id=owner, capability=capability, provider_id=provider_id,
            notice_version=version or NOTICE_VERSIONS[capability], accepted_at=datetime.now(UTC),
            revoked_at=datetime.now(UTC) if revoked else None,
        ))
