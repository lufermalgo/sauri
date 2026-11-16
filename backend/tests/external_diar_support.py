"""Fakes shared by the U5.2 tests: a Deepgram-shaped speaker provider on a loopback port.

Only the documented ``/v1/listen`` answer shape is reproduced (words with ``speaker``, ``start`` and ``end``
in seconds). The audio is synthetic and never decoded. Nothing here speaks for the real provider: Spanish
quality and limits stay NO VERIFICADO until U10.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse


def load_native_diar(name: str) -> ModuleType:
    """Import ``backend/diar-engine/native_main.py`` under ``name`` (as the gateway tests do)."""
    path = Path(__file__).resolve().parents[1] / "diar-engine" / "native_main.py"
    sys.path[:0] = [str(path.parent), str(path.parent.parent / "engine-common")]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# speaker (None = unlabelled), text, start_s, end_s on the part clock
DgWord = tuple[int | None, str, float, float]


@dataclass
class FakeDeepgram:
    """``words_for(n)`` answers the n-th request (0-based); failures are switches."""

    words_for: Callable[[int], list[DgWord]] = field(
        default=lambda n: [(0, "Hola", 0.1, 0.4), (1, "mundo.", 0.45, 0.9)]
    )
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    hang: bool = False
    authorizations: list[str | None] = field(default_factory=list)
    queries: list[dict[str, list[str]]] = field(default_factory=list)
    bodies: list[int] = field(default_factory=list)  # size of each uploaded body
    requests: int = 0

    def app(self) -> FastAPI:
        provider = FastAPI(docs_url=None, openapi_url=None)

        @provider.post("/v1/listen")
        async def listen(request: Request) -> Response:
            index = self.requests
            self.requests += 1
            self.authorizations.append(request.headers.get("authorization"))
            self.queries.append(parse_qs(request.url.query))
            self.bodies.append(len(await request.body()))
            if self.hang:
                await asyncio.sleep(60)
            if self.status != 200:
                return JSONResponse({"err_code": "synthetic"}, status_code=self.status, headers=self.headers)
            words = self.words_for(index)
            document: dict[str, Any] = {
                "metadata": {"duration": 3.0},
                "results": {"channels": [{"alternatives": [{
                    "transcript": " ".join(text for _s, text, _a, _b in words),
                    "words": [
                        {"word": text, "start": start, "end": end, "confidence": 0.9,
                         **({} if speaker is None else {"speaker": speaker})}
                        for speaker, text, start, end in words
                    ],
                }]}]},
            }
            return JSONResponse(document)

        return provider
