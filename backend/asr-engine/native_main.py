"""Host-native ASR service using mlx-whisper on Apple silicon."""

from __future__ import annotations

import hashlib
import hmac
import logging
import math
import os
import secrets
import tempfile
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

logger = logging.getLogger("asr-engine-native")
logging.basicConfig(level=logging.INFO)

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ROOT_USER", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "sauri-recordings")
MINIO_AUDIO_PREFIX = os.environ.get("MINIO_AUDIO_PREFIX", "recordings/")
ENGINE_TOKEN_PATH = Path(os.environ.get("SAURI_ENGINE_TOKEN_FILE", Path.home() / ".config" / "sauri" / "engine_token"))
RECORDING_CAPABILITY_KEY_PATH = Path(
    os.environ.get(
        "SAURI_RECORDING_CAPABILITY_KEY_FILE",
        Path.home() / ".config" / "sauri" / "recording_capability_key",
    )
)
RECORDING_CAPABILITY_TTL_SECONDS = 60
MODEL_ID = os.environ.get("ASR_MODEL", "mlx-community/whisper-large-v3-turbo")
MODEL_DEVICE = "mlx"
# QA opt-in until the acoustic qualification protocol has passed.
ACOUSTIC_VALIDATION_ENABLED = os.environ.get("ASR_ACOUSTIC_VALIDATION", "0") == "1"
voice_activity_detector: Any = None
_bearer_scheme = HTTPBearer(auto_error=False)
_bearer_dependency = Depends(_bearer_scheme)

transcribe_audio: Any = None
s3_client: Any = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Load the MLX inference function and initialize MinIO at process start."""
    global transcribe_audio, s3_client, voice_activity_detector
    try:
        import mlx_whisper

        transcribe_audio = mlx_whisper.transcribe
    except Exception as exc:
        raise RuntimeError("Unable to initialize mlx-whisper") from exc
    s3_client = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
    )
    logger.info("Native ASR initialized (model=%s)", MODEL_ID)
    yield
    transcribe_audio = None
    s3_client = None
    voice_activity_detector = None


app = FastAPI(title="Sauri Native ASR Engine", version="1.0.0", lifespan=lifespan)


class TranscribeRequest(BaseModel):
    audio_ref: str
    language: str = "es-CO"


class WordInterval(BaseModel):
    text: str
    start_ms: int
    end_ms: int


class Segment(BaseModel):
    text: str
    start_ms: int
    end_ms: int
    alignment: list[WordInterval] | None = None


class TranscribeResponse(BaseModel):
    segments: list[Segment]
    language: str


def _require_engine_token(
    credentials: HTTPAuthorizationCredentials | None = _bearer_dependency,
) -> None:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        expected = ENGINE_TOKEN_PATH.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Engine authentication unavailable") from exc
    if not expected:
        raise HTTPException(status_code=503, detail="Engine authentication unavailable")
    if not secrets.compare_digest(credentials.credentials, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _validate_audio_ref(audio_ref: str) -> None:
    parts = audio_ref.split("/")
    if (
        not MINIO_AUDIO_PREFIX.endswith("/")
        or not audio_ref.startswith(MINIO_AUDIO_PREFIX)
        or audio_ref.startswith("/")
        or "\\" in audio_ref
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise HTTPException(status_code=400, detail="Invalid audio reference")


def _require_recording_capability(audio_ref: str, capability: str | None) -> None:
    if capability is None:
        raise HTTPException(status_code=403, detail="Recording authorization required")
    try:
        secret = RECORDING_CAPABILITY_KEY_PATH.read_bytes()
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Recording authorization unavailable") from exc
    if not secret:
        raise HTTPException(status_code=503, detail="Recording authorization unavailable")
    try:
        expiry_text, signature = capability.split(".", maxsplit=1)
        expires_at = int(expiry_text)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=403, detail="Invalid recording authorization") from exc
    now = int(time.time())
    if expires_at <= now or expires_at > now + RECORDING_CAPABILITY_TTL_SECONDS:
        raise HTTPException(status_code=403, detail="Expired recording authorization")
    message = f"{audio_ref}\n{expires_at}".encode()
    expected = hmac.new(secret, message, hashlib.sha256).hexdigest()
    if not secrets.compare_digest(signature, expected):
        raise HTTPException(status_code=403, detail="Invalid recording authorization")


def _download_audio(audio_ref: str) -> str:
    if s3_client is None:
        raise RuntimeError("Object store is not initialized")
    suffix = Path(audio_ref).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
        audio_path = temp.name
    downloaded = False
    try:
        s3_client.download_file(MINIO_BUCKET, audio_ref, audio_path)
        downloaded = True
    except Exception as exc:
        raise RuntimeError("Audio download failed") from exc
    finally:
        if not downloaded:
            with suppress(OSError):
                os.unlink(audio_path)
    return audio_path


def _language_code(language: str) -> str | None:
    base = language.split("-", maxsplit=1)[0].strip().lower()
    return base or None


def _load_voice_activity_detector() -> Any:
    """Reuse the already-installed powerset checkpoint; never download a model."""
    import torch
    from pyannote.audio import Model
    from pyannote.audio.pipelines import VoiceActivityDetection

    cache = Path.home() / ".cache/torch/pyannote/models--pyannote--segmentation-3.0"
    configured = os.environ.get("ASR_VAD_MODEL_PATH")
    if configured:
        checkpoint = Path(configured)
    else:
        revision = (cache / "refs/main").read_text(encoding="utf-8").strip()
        if not revision or Path(revision).name != revision:
            raise RuntimeError("Invalid cached segmentation revision")
        checkpoint = cache / "snapshots" / revision / "pytorch_model.bin"
    if not checkpoint.is_file():
        raise RuntimeError("Existing segmentation checkpoint is unavailable")
    model = Model.from_pretrained(str(checkpoint))
    if not model.specifications.powerset:
        raise RuntimeError("Only the existing powerset segmentation is supported")
    detector = VoiceActivityDetection(segmentation=model)
    # Powerset uses the library's fixed 0.5 decision; do not discard brief speech
    # or fill gaps. These zero-duration settings do not introduce a voice cutoff.
    detector.instantiate({"min_duration_on": 0.0, "min_duration_off": 0.0})
    detector.to(torch.device(os.environ.get("DIARIZATION_DEVICE", "mps")))
    return detector


def _detect_speech(audio_path: str) -> tuple[Any, list[tuple[int, int]], int]:
    """Decode once in memory; retain absolute offsets and no clips or payload cache."""
    import numpy as np
    import torch
    from mlx_whisper.audio import SAMPLE_RATE, load_audio

    global voice_activity_detector
    if voice_activity_detector is None:
        voice_activity_detector = _load_voice_activity_detector()
    waveform = load_audio(audio_path)
    duration_ms = int(len(waveform) * 1000 / SAMPLE_RATE)
    annotation = voice_activity_detector(
        {
            "waveform": torch.from_numpy(np.array(waveform)).unsqueeze(0),
            "sample_rate": SAMPLE_RATE,
        }
    )
    regions = [(int(region.start * 1000), int(region.end * 1000)) for region in annotation.get_timeline().support()]
    if duration_ms <= 0 or any(not (0 <= start < end <= duration_ms) for start, end in regions):
        raise RuntimeError("Invalid speech activity coverage")
    return waveform, regions, duration_ms


def _aligned_segments(segment: dict[str, Any], source: Segment) -> list[Segment]:
    """Use exact model word boundaries or preserve the entire valid source."""
    words = segment.get("words")
    if not isinstance(words, list) or not words:
        return [source]
    try:
        texts = [str(word["word"]) for word in words]
        texts[0] = texts[0].lstrip()
        texts[-1] = texts[-1].rstrip()
        if "".join(texts) != source.text or any(not text.strip() for text in texts):
            return [source]
        aligned = []
        for text, word in zip(texts, words, strict=True):
            start, end = float(word["start"]), float(word["end"])
            if not math.isfinite(start) or not math.isfinite(end):
                return [source]
            start_ms, end_ms = int(start * 1000), int(end * 1000)
            if not source.start_ms <= start_ms < end_ms <= source.end_ms:
                return [source]
            # Preserve real overlaps, but never publish reversed word ordering.
            # Invalid optional alignment falls back as a whole, without sorting
            # words, moving boundaries or losing text from the admitted source.
            if aligned and (start_ms < aligned[-1].start_ms or end_ms < aligned[-1].end_ms):
                return [source]
            aligned.append(Segment(text=text, start_ms=start_ms, end_ms=end_ms))
        return aligned
    except (KeyError, TypeError, ValueError, OverflowError):
        return [source]


def _admit_segments(
    result: dict[str, Any], regions: list[tuple[int, int]] | None, duration_ms: int | None
) -> list[Segment]:
    segments = []
    for segment in result.get("segments", []):
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        start, end = float(segment["start"]), float(segment["end"])
        if not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end:
            raise ValueError("Invalid source segment timing")
        source = Segment(text=text, start_ms=int(start * 1000), end_ms=int(end * 1000))
        # Decoder no_speech_prob was near zero even for noise in qualification.
        # Only actual model VAD coverage, never that textual decoder score, gates.
        if (
            regions is not None
            and duration_ms is not None
            and source.end_ms <= duration_ms
            and not any(min(source.end_ms, end) > max(source.start_ms, begin) for begin, end in regions)
        ):
            continue
        # Alignment is part of the QA mode; the legacy response stays unchanged.
        if regions is not None:
            aligned = _aligned_segments(segment, source)
            if aligned != [source]:
                source.alignment = [WordInterval(text=word.text, start_ms=word.start_ms, end_ms=word.end_ms)
                                    for word in aligned]
            elif isinstance(segment.get("words"), list) and len(segment["words"]) == 1:
                # The single aligned word can equal its parent; still validate it.
                word = segment["words"][0]
                if (word.get("word", "").strip() == source.text
                    and word.get("start") == source.start_ms / 1000
                    and word.get("end") == source.end_ms / 1000):
                    source.alignment = [WordInterval(text=source.text, start_ms=source.start_ms, end_ms=source.end_ms)]
        segments.append(source)
    return segments


@app.post("/transcribe", response_model=TranscribeResponse, response_model_exclude_none=True)
async def transcribe(
    request: TranscribeRequest,
    _authorized: None = Depends(_require_engine_token),
    recording_capability: str | None = Header(default=None, alias="X-Sauri-Recording-Capability"),
) -> TranscribeResponse:
    _validate_audio_ref(request.audio_ref)
    _require_recording_capability(request.audio_ref, recording_capability)
    if transcribe_audio is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    try:
        audio_path = _download_audio(request.audio_ref)
    except Exception as exc:
        logger.error("Audio download failed")
        raise HTTPException(status_code=500, detail="Audio download failed") from exc

    try:
        audio_input: Any = audio_path
        regions: list[tuple[int, int]] | None = None
        duration_ms: int | None = None
        if ACOUSTIC_VALIDATION_ENABLED:
            audio_input, regions, duration_ms = _detect_speech(audio_path)
        result = transcribe_audio(
            audio_input,
            path_or_hf_repo=MODEL_ID,
            language=_language_code(request.language),
            # Align against speech instead of retaining decoder-only boundaries;
            # do not carry text across windows and reinforce repetitions in silence.
            word_timestamps=True,
            condition_on_previous_text=False,
            hallucination_silence_threshold=2.0,
            verbose=False,
        )
        segments = _admit_segments(result, regions, duration_ms)
        language = str(result.get("language") or request.language)
        return TranscribeResponse(segments=segments, language=language)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Transcription failed")
        raise HTTPException(status_code=500, detail="Transcription failed") from exc
    finally:
        with suppress(OSError):
            os.unlink(audio_path)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
