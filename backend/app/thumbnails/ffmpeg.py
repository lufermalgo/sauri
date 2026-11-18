"""Frame selection and the ffmpeg/ffprobe calls behind a recording thumbnail.

The media is read through a short-lived signed URL, never downloaded whole. The
URL is a credential: it is never logged and any URL in tool output is redacted.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.meetings.recorded_at import parse_timestamp

logger = logging.getLogger(__name__)

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

TARGET_SECONDS = 600.0
THUMBNAIL_WIDTH = 320
JPEG_QUALITY = 5  # mjpeg -q:v scale (2 best .. 31 worst); 5 is about JPEG quality 80
PROBE_TIMEOUT_SECONDS = 60.0
EXTRACT_TIMEOUT_SECONDS = 180.0
MAX_FRAME_BYTES = 1_000_000
MAX_FRAME_ATTEMPTS = 3

# Uploaded media is untrusted input. Only plain network reads and ordinary media
# containers are allowed, so a crafted playlist or concat file cannot make ffmpeg
# read local files or reach other hosts.
ALLOWED_PROTOCOLS = "http,https,tcp,tls,crypto"
ALLOWED_FORMATS = (
    "matroska,webm,mov,mp4,m4a,3gp,3g2,mj2,avi,asf,flv,mpegts,mpeg,ogg,wav,mp3,aac,flac,aiff"
)

_URL = re.compile(r"\w+://\S+")
_JPEG_MAGIC = b"\xff\xd8\xff"


class MediaToolError(Exception):
    """ffmpeg or ffprobe ran but did not produce a usable result (bad media, timeout)."""


@dataclass(frozen=True)
class MediaProbe:
    """What the thumbnail needs to know about a media object."""

    duration_seconds: float | None
    has_video: bool
    creation_time: datetime | None = None


# Container tags that say when a file was made, best first. Apple's keeps the real local offset;
# `creation_time` is the generic one (mp4, mov, mkv, webm); `DATE` is Matroska's, often a date only.
CREATION_TAGS = ("com.apple.quicktime.creationdate", "creation_time", "date")


def _quicktime_offset_fixed(text: str) -> str:
    """Apple writes the offset as +0100; fromisoformat reads +01:00 on every supported Python."""
    if len(text) > 5 and text[-5] in "+-" and text[-4:].isdigit():
        return f"{text[:-2]}:{text[-2:]}"
    return text


def read_creation_time(document: dict[str, Any]) -> datetime | None:
    """When the container says the media was created, or None. Only these tags are ever read."""
    tags = (document.get("format") or {}).get("tags")
    if not isinstance(tags, dict):
        return None
    lowered = {str(key).lower(): value for key, value in tags.items() if isinstance(value, str)}
    for name in CREATION_TAGS:
        raw = lowered.get(name)
        if raw is None:
            continue
        parsed = parse_timestamp(_quicktime_offset_fixed(raw.strip()))
        if parsed is not None:
            return parsed
    return None


def select_frame_time(duration_seconds: float | None) -> float | None:
    """Pick the moment to show: minute 10, or the middle of a shorter recording.

    The last frame is avoided on purpose: it is often a "stopped sharing" screen.
    Returns None when the duration is unknown or not positive.
    """
    if duration_seconds is None or not math.isfinite(duration_seconds) or duration_seconds <= 0:
        return None
    if duration_seconds >= TARGET_SECONDS:
        return TARGET_SECONDS
    return duration_seconds / 2


def frame_time_candidates(duration_seconds: float | None) -> list[float]:
    """Moments to try in order; later ones only matter when an earlier seek yields no frame.

    With an unknown duration the target is tried first, then the start of the media.
    """
    chosen = select_frame_time(duration_seconds)
    if chosen is None:
        times = [TARGET_SECONDS, 0.0]
    else:
        times = [chosen]
        if duration_seconds is not None and chosen != duration_seconds / 2:
            times.append(duration_seconds / 2)
        times.append(0.0)
    return times[:MAX_FRAME_ATTEMPTS]


def parse_probe(output: bytes) -> MediaProbe:
    """Read ffprobe JSON; a missing or non-numeric duration (typical of live webm) is None."""
    try:
        document: dict[str, Any] = json.loads(output)
    except ValueError as exc:
        raise MediaToolError("ffprobe returned invalid JSON") from exc
    if not isinstance(document, dict):
        raise MediaToolError("ffprobe returned an unexpected document")

    duration: float | None = None
    raw_duration = (document.get("format") or {}).get("duration")
    try:
        parsed = float(raw_duration) if raw_duration is not None else None
    except (TypeError, ValueError):
        parsed = None
    if parsed is not None and math.isfinite(parsed) and parsed > 0:
        duration = parsed

    has_video = any(
        stream.get("codec_type") == "video" and not (stream.get("disposition") or {}).get("attached_pic")
        for stream in document.get("streams") or []
        if isinstance(stream, dict)
    )
    return MediaProbe(duration_seconds=duration, has_video=has_video, creation_time=read_creation_time(document))


def _input_options(source_url: str) -> list[str]:
    # Local paths are confined by the service; never allow network protocols in local mode.
    protocols = "file" if Path(source_url).is_absolute() else ALLOWED_PROTOCOLS
    return ["-protocol_whitelist", protocols, "-format_whitelist", ALLOWED_FORMATS]


def probe_command(source_url: str) -> list[str]:
    return [
        FFPROBE, "-v", "error", *_input_options(source_url), "-print_format", "json",
        "-show_entries",
        "format=duration:format_tags=" + ",".join(CREATION_TAGS)
        + ":stream=codec_type:stream_disposition=attached_pic",
        source_url,
    ]


def frame_command(source_url: str, seconds: float) -> list[str]:
    """One scaled JPEG frame on stdout. `-ss` before `-i` seeks in the container, not by decoding."""
    return [
        FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", *_input_options(source_url),
        "-ss", f"{seconds:.3f}", "-i", source_url,
        "-map", "0:v:0", "-frames:v", "1", "-an", "-sn", "-dn",
        "-vf", f"scale={THUMBNAIL_WIDTH}:-2", "-q:v", str(JPEG_QUALITY),
        "-f", "mjpeg", "pipe:1",
    ]


def _redact(text: bytes, source: str = "") -> str:
    """First stderr line with URLs removed (signed URLs are credentials)."""
    decoded = text.decode("utf-8", errors="replace")
    if Path(source).is_absolute():
        decoded = decoded.replace(source, "<media>")
    first = decoded.strip().splitlines()[:1]
    return _URL.sub("<url>", first[0])[:200] if first else ""


async def _run(command: list[str], timeout_seconds: float) -> tuple[bytes, bytes, int]:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout_seconds)
    except TimeoutError as exc:
        raise MediaToolError(f"{command[0]} timed out after {timeout_seconds:.0f}s") from exc
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    return stdout, stderr, process.returncode if process.returncode is not None else -1


async def probe_media(source_url: str) -> MediaProbe:
    """Duration and video presence of the object behind `source_url`."""
    stdout, stderr, code = await _run(probe_command(source_url), PROBE_TIMEOUT_SECONDS)
    if code != 0:
        raise MediaToolError(f"ffprobe exited with {code}: {_redact(stderr, source_url)}")
    return parse_probe(stdout)


async def extract_frame(source_url: str, seconds: float) -> bytes:
    """Cut one JPEG frame at `seconds`; raises MediaToolError when there is no frame to cut."""
    stdout, stderr, code = await _run(frame_command(source_url, seconds), EXTRACT_TIMEOUT_SECONDS)
    if code != 0:
        raise MediaToolError(f"ffmpeg exited with {code}: {_redact(stderr, source_url)}")
    if not stdout.startswith(_JPEG_MAGIC) or len(stdout) > MAX_FRAME_BYTES:
        raise MediaToolError("ffmpeg produced no valid frame")
    return stdout


async def extract_best_frame(
    source_url: str, duration_seconds: float | None, offset_seconds: float = 0.0
) -> bytes | None:
    """First frame that can be cut among the candidate moments, or None.

    `offset_seconds` is how far into the recording the media starts (a separate video file).
    """
    for seconds in frame_time_candidates(duration_seconds):
        try:
            return await extract_frame(source_url, max(0.0, seconds - offset_seconds))
        except MediaToolError as exc:
            logger.info("No thumbnail frame at %.0fs: %s", seconds, exc)
    return None
