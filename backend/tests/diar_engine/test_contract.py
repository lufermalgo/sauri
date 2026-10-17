"""Contract test for the diar-engine FastAPI service.

# Feature: speaker-identification, Task 14.1
# Validates: Requirements 3.1, 3.3

Verifies the HTTP contract of the Local_Diarization_Service:
  - POST /diarize: request {"audio_ref": str} → response {"segments": [...], "num_speakers": int}
  - GET /health → {"status": "ok"}

Uses httpx.AsyncClient with ASGITransport to test the FastAPI app directly
(same pattern as asr-engine integration tests).

Test isolation policy
---------------------
The production diar-engine (`diar-engine/main.py`) uses the REAL pyannote.audio
pipeline and the REAL MinIO/S3 object store. Following the same discipline as the
asr-engine contract test, this contract test injects test doubles ONLY here in the
test for the two external I/O boundaries:

  * the speaker-diarization model (`main.diarization_pipeline`), and
  * the object-store download (`main._download_audio_from_s3`).

It also registers lightweight stand-ins for the heavy ML modules (`torch`,
`pyannote.audio`) in ``sys.modules`` so the service module is importable in a
local venv that has not installed the multi-gigabyte ML stack. Production code is
untouched and remains 100% real and deployable.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

# Add diar-engine directory to sys.path so we can import its main module.
# This mirrors how the asr-engine service is structured as a separate service
# directory outside the main app package.
_DIAR_ENGINE_DIR = Path(__file__).resolve().parent.parent.parent / "diar-engine"
sys.path.insert(0, str(_DIAR_ENGINE_DIR))


# ---------------------------------------------------------------------------
# Test-only stand-ins for heavy ML modules.
#
# The local venv is not required to carry torch / pyannote.audio (multi-GB).
# If they are genuinely installed, the real modules are used as-is. Otherwise
# we register minimal modules so `from main import app` succeeds. These
# stand-ins are NEVER imported by production at runtime in deployment, where
# the real wheels are installed via diar-engine/requirements.txt.
# ---------------------------------------------------------------------------


def _ensure_module(name: str, factory: Callable[[], None]) -> None:
    """Register a stand-in module under ``name`` if it cannot be imported."""
    if name in sys.modules:
        return
    try:  # pragma: no cover - exercised only when the real lib is present
        __import__(name)
    except ImportError:
        factory()


def _install_torch_stub() -> None:
    torch_stub = cast(Any, types.ModuleType("torch"))
    torch_stub.device = lambda *args, **kwargs: ("torch.device", args, kwargs)
    sys.modules["torch"] = torch_stub


def _install_pyannote_stub() -> None:
    pyannote_pkg = cast(
        Any, sys.modules.get("pyannote") or types.ModuleType("pyannote")
    )
    pyannote_audio = cast(Any, types.ModuleType("pyannote.audio"))

    class Pipeline:  # minimal stand-in for the symbol imported by main
        @staticmethod
        def from_pretrained(*args: Any, **kwargs: Any) -> None:  # pragma: no cover - not used here
            raise RuntimeError("stub pipeline; inject main.diarization_pipeline in tests")

    pyannote_audio.Pipeline = Pipeline
    pyannote_pkg.audio = pyannote_audio
    sys.modules["pyannote"] = pyannote_pkg
    sys.modules["pyannote.audio"] = pyannote_audio


_ensure_module("torch", _install_torch_stub)
_ensure_module("pyannote.audio", _install_pyannote_stub)

import httpx  # noqa: E402
import main  # type: ignore[import-not-found]  # noqa: E402
from main import app  # noqa: E402

# ---------------------------------------------------------------------------
# Fake diarization pipeline (test double for the pyannote model boundary).
# ---------------------------------------------------------------------------


class _FakeTurn:
    """Mimics a pyannote Segment with start/end expressed in seconds."""

    def __init__(self, start: float, end: float) -> None:
        self.start = start
        self.end = end


class _FakeAnnotation:
    """Mimics a pyannote Annotation supporting itertracks(yield_label=True)."""

    def __init__(self, tracks: list[tuple[float, float, str]]) -> None:
        self._tracks = tracks

    def itertracks(self, yield_label: bool = False) -> Any:
        for start, end, speaker in self._tracks:
            turn = _FakeTurn(start, end)
            if yield_label:
                yield turn, None, speaker
            else:
                yield turn, None


class _FakePipeline:
    """Callable test double standing in for a loaded pyannote pipeline."""

    def __call__(self, audio_path: str) -> _FakeAnnotation:
        # Silence/empty reference → no speakers detected (valid empty contract).
        if "silence" in str(audio_path):
            return _FakeAnnotation([])
        # Two speakers, intentionally out of order to exercise start_ms sorting.
        return _FakeAnnotation(
            [
                (2.0, 4.0, "SPEAKER_01"),
                (0.0, 1.5, "SPEAKER_00"),
                (4.5, 6.0, "SPEAKER_00"),
            ]
        )


@pytest.fixture
def async_client(monkeypatch: pytest.MonkeyPatch) -> httpx.AsyncClient:
    """httpx AsyncClient bound to the diar-engine app with injected doubles."""
    # Inject the fake model in place of the real (unloaded) pyannote pipeline.
    monkeypatch.setattr(main, "diarization_pipeline", _FakePipeline())
    # Replace the object-store download with a no-network stand-in that returns
    # the audio_ref itself as the "local path" so the fake pipeline can branch.
    monkeypatch.setattr(main, "_download_audio_from_s3", lambda audio_ref: audio_ref)

    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


class TestContratoDiarEngine:
    """Verifies the HTTP contract of the Local_Diarization_Service (diar-engine)."""

    # -------------------------------------------------------------------
    # POST /diarize — Validates: Requirement 3.1, 3.3
    # -------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_post_diarize_respuesta_con_segmentos(
        self, async_client: httpx.AsyncClient
    ) -> None:
        """POST /diarize with a valid audio_ref returns segments and num_speakers.

        Contract:
          Request:  {"audio_ref": "test/audio.webm"}
          Response: {"segments": [{"speaker": str, "start_ms": int, "end_ms": int}, ...],
                     "num_speakers": int}
        """
        async with async_client as client:
            response = await client.post(
                "/diarize",
                json={"audio_ref": "test/audio.webm"},
            )

        assert response.status_code == 200

        data = response.json()

        # Verify top-level structure
        assert "segments" in data
        assert "num_speakers" in data
        assert isinstance(data["segments"], list)
        assert isinstance(data["num_speakers"], int)
        assert data["num_speakers"] >= 0

        # If segments are present, verify each segment's structure
        for segment in data["segments"]:
            assert "speaker" in segment
            assert "start_ms" in segment
            assert "end_ms" in segment
            assert isinstance(segment["speaker"], str)
            assert isinstance(segment["start_ms"], int)
            assert isinstance(segment["end_ms"], int)
            assert segment["start_ms"] >= 0
            assert segment["end_ms"] >= segment["start_ms"]

        # Contract: segments must be ordered ascending by start_ms.
        starts = [segment["start_ms"] for segment in data["segments"]]
        assert starts == sorted(starts)

        # num_speakers must equal the count of distinct speaker labels.
        distinct = {segment["speaker"] for segment in data["segments"]}
        assert data["num_speakers"] == len(distinct)

    @pytest.mark.asyncio
    async def test_post_diarize_respuesta_vacia_valida(
        self, async_client: httpx.AsyncClient
    ) -> None:
        """POST /diarize can return segments: [] with num_speakers: 0 (no speakers)."""
        async with async_client as client:
            response = await client.post(
                "/diarize",
                json={"audio_ref": "test/silence.webm"},
            )

        assert response.status_code == 200

        data = response.json()
        assert "segments" in data
        assert "num_speakers" in data
        assert isinstance(data["segments"], list)
        assert isinstance(data["num_speakers"], int)
        assert data["segments"] == []
        assert data["num_speakers"] == 0

    # -------------------------------------------------------------------
    # GET /health — Validates: Requirement 3.3
    # -------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_health_endpoint(self, async_client: httpx.AsyncClient) -> None:
        """GET /health devuelve {"status": "ok"}."""
        async with async_client as client:
            response = await client.get("/health")

        assert response.status_code == 200

        data = response.json()
        assert data == {"status": "ok"}
