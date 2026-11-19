"""Parakeet backend of the ASR gateway: ``fluidaudiocli`` (FluidAudio, Core ML on the Neural Engine).

One job is one subprocess over the whole normalized recording (16 kHz mono PCM16; no VAD pre-chunking, as the
benchmark ran it), started in its own process group through ``sauri_engine_common.process_group`` so a caller
that leaves, a timeout or an engine shutdown kills it. Nothing here downloads anything:

* the binary must match ``provenance.json`` (pinned source commit, SHA-256 of the file), and an adopted binary
  must be one of the known builds of ``engine-hashes.json``;
* the model directory is the one the host service verified (``select_local_model`` checks its manifest);
* the model is passed with ``--local-model-dir`` (the CLI's "never downloads" option; ``--model-dir`` may fetch
  and list files on Hugging Face), and the subprocess also gets a registry URL that cannot be reached.

The CLI output is converted to the contract-v2 words and segments and then judged by ``sanity_check``: language
drift (the stock v3 model slips into English), empty output, repetition loops and broken timestamps. A rejected
output fails the transcription (``ParakeetRejected``, mapped by ``failure``): Parakeet is the one model of the
request and no other model transcribes the audio again. The user can retry, or choose Whisper in Settings and
regenerate. Thresholds come from the environment with the safe defaults below.

Logs carry reason codes and counts only, never transcript text or the CLI's stderr.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import wave
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from asr_assets import digest, manifest_path
from asr_external import SEGMENT_GAP_MS, SEGMENT_MAX_MS, SEGMENT_MAX_WORDS
from sauri_engine_common import cancellation
from sauri_engine_common.process_group import run as run_group
from whisper_words import Segment, Word, WordsResult, repair_word_timing

logger = logging.getLogger("asr-engine-parakeet")

ENGINE_NAME: Final = "fluidaudio"
CATALOG_ENGINE: Final = "fluidaudio"
MODEL_ID: Final = "parakeet-tdt-0.6b-v3-ultra-coreml"
DEVICE: Final = "coreml-ane"
BINARY_NAME: Final = "fluidaudiocli"
# The 25 languages of Parakeet-TDT-0.6B-v3 (model card). Any other language is refused (``language_not_supported``).
SUPPORTED_LANGUAGES: Final = frozenset(
    [
        "en",
        "de",
        "fr",
        "es",
        "it",
        "pt",
        "ru",
        "uk",
        "hr",
        "sl",
        "lv",
        "lt",
        "et",
        "fi",
        "sv",
        "da",
        "nl",
        "pl",
        "cs",
        "sk",
        "hu",
        "ro",
        "bg",
        "el",
        "mt",
    ]
)
# Stopwords that are not words of the other supported languages: a Spanish (or German, French...) transcript
# that contains many of them has drifted into English (the stock v3 model does it on 10.5 % of the words; the
# ultra build on 0.2 %).
ENGLISH_STOPWORDS: Final = frozenset(
    [
        "the",
        "and",
        "that",
        "this",
        "with",
        "you",
        "they",
        "have",
        "what",
        "there",
        "would",
        "been",
        "which",
        "their",
        "about",
        "from",
        "your",
        "because",
        "just",
        "but",
        "not",
        "are",
        "were",
        "should",
        "could",
        "these",
        "those",
        "when",
        "where",
        "then",
        "than",
        "them",
        "into",
        "also",
        "only",
        "very",
        "some",
        "other",
        "our",
        "out",
        "how",
        "who",
        "his",
    ]
)
REPEAT_MIN_WORDS: Final = 12
MIN_WORDS_FOR_RATE: Final = 40
TOKEN_STRIP: Final = re.compile(r"^\W+|\W+$")

# Reason codes of a refused or rejected run (content-free; logged, never returned with any text).
REASON_LANGUAGE_AUTO: Final = "parakeet_language_auto"
REASON_LANGUAGE_UNSUPPORTED: Final = "parakeet_language_unsupported"
REASON_UNAVAILABLE: Final = "parakeet_unavailable"
REASON_FAILED: Final = "parakeet_failed"
REASON_TIMEOUT: Final = "parakeet_timeout"
REASON_INVALID: Final = "parakeet_invalid_output"
REASON_EMPTY: Final = "parakeet_empty_output"
REASON_DRIFT: Final = "parakeet_language_drift"
REASON_REPETITION: Final = "parakeet_repetition"
REASON_TIMESTAMPS: Final = "parakeet_timestamps"


class ParakeetRejected(Exception):  # noqa: N818 - the request fails with the code ``failure`` gives
    """Parakeet cannot or should not answer this audio; ``reason`` is the content-free code to log."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def serves_language(language: str) -> bool:
    """Parakeet needs a known language of its 25 (it does not detect the language: ``auto`` is refused)."""
    return language in SUPPORTED_LANGUAGES


def failure(reason: str) -> tuple[int, str]:
    """The HTTP status and the stable code a request gets when Parakeet refused or rejected its audio."""
    if reason in (REASON_LANGUAGE_AUTO, REASON_LANGUAGE_UNSUPPORTED):
        return 422, "language_not_supported"
    if reason == REASON_UNAVAILABLE:
        return 503, "model_failed"
    return 500, "model_failed"


@dataclass(frozen=True)
class GuardConfig:
    english_rate_max: float = 0.01
    repeat_min_repeats: int = 6
    nonmonotonic_ratio_max: float = 0.005
    out_of_range_ratio_max: float = 0.01


@dataclass(frozen=True)
class ParakeetResult:
    words: WordsResult
    segments: tuple[Segment, ...]
    confidence: float | None
    rtfx: float | None
    cli_ms: int
    english_rate: float


# --- configuration ------------------------------------------------------------------------------------


def _float_env(name: str, default: float, low: float, high: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number") from None
    if not low <= value <= high or value != value:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def guard_config() -> GuardConfig:
    """Thresholds of the sanity guard from the environment; an invalid value is a startup error, not a default."""
    return GuardConfig(
        english_rate_max=_float_env("SAURI_ASR_PARAKEET_ENGLISH_RATE_MAX", 0.01, 0.0, 1.0),
        repeat_min_repeats=int(_float_env("SAURI_ASR_PARAKEET_REPEAT_MIN_REPEATS", 6, 2, 1000)),
        nonmonotonic_ratio_max=_float_env("SAURI_ASR_PARAKEET_NONMONOTONIC_MAX_RATIO", 0.005, 0.0, 1.0),
    )


def default_engine() -> str:
    """``auto`` (``local:default`` is Parakeet when it is installed and healthy, else Whisper) or ``whisper``.

    It decides which model ``local:default`` means before a request runs; it never moves a running request.
    """
    value = os.environ.get("SAURI_ASR_DEFAULT_ENGINE", "auto")
    if value not in {"auto", "whisper"}:
        raise ValueError("SAURI_ASR_DEFAULT_ENGINE must be auto or whisper")
    return value


def cli_timeout_s(audio_ms: int) -> float:
    """Wall-clock limit of one Parakeet run. A hour of audio takes ~20 s warm and ~90 s on the very first run."""
    override = os.environ.get("SAURI_ASR_PARAKEET_TIMEOUT_S")
    if override is not None:
        return _float_env("SAURI_ASR_PARAKEET_TIMEOUT_S", 0.0, 1.0, 86_400.0)
    return min(420.0, 90.0 + audio_ms / 1000 * 0.05)


def parakeet_home() -> Path:
    return Path(
        os.environ.get(
            "SAURI_PARAKEET_HOME",
            "~/.local/share/sauri/native-engines/parakeet",
        )
    ).expanduser()


def binary_path() -> Path:
    """``SAURI_PARAKEET_CLI`` (the desktop app's runtime copy, next to its resource bundle) or ``<home>/bin``."""
    override = os.environ.get("SAURI_PARAKEET_CLI")
    return Path(override).expanduser() if override else parakeet_home() / "bin" / BINARY_NAME


def provenance_path() -> Path:
    return parakeet_home() / "provenance.json"


def warm_marker_path() -> Path:
    return parakeet_home() / "warm.json"


def load_pins() -> dict[str, Any]:
    """The ``parakeet`` section of engine-hashes.json: pinned source commit and known binary builds."""
    pins = json.loads(manifest_path().read_text())["parakeet"]
    commit = pins.get("source_commit")
    known = pins.get("known_binary_sha256")
    if (
        not isinstance(commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", commit) is None
        or not isinstance(known, list)
        or any(not isinstance(item, str) or re.fullmatch(r"[0-9a-f]{64}", item) is None for item in known)
    ):
        raise ValueError("Invalid Parakeet pins")
    return dict(pins)


# --- binary verification ------------------------------------------------------------------------------

_digest_cache: dict[str, tuple[int, int, str]] = {}


def _binary_digest(path: Path) -> str:
    info = path.stat()
    cached = _digest_cache.get(str(path))
    if cached is not None and cached[:2] == (info.st_size, info.st_mtime_ns):
        return cached[2]
    value = digest(path)
    _digest_cache[str(path)] = (info.st_size, info.st_mtime_ns, value)
    return value


def verify_binary() -> str:
    """Raise ``ParakeetRejected`` unless the CLI is the pinned one; returns its SHA-256.

    The provenance (written by ``install-parakeet-engine.sh``) must name the pinned source commit and the exact
    file; an adopted binary (built elsewhere) must additionally be one of the known builds.
    """
    path = binary_path()
    try:
        pins = load_pins()
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ParakeetRejected(REASON_UNAVAILABLE)
        record = json.loads(provenance_path().read_text())
        actual = _binary_digest(path)
    except ParakeetRejected:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        raise ParakeetRejected(REASON_UNAVAILABLE) from None
    if (
        not isinstance(record, dict)
        or record.get("source_commit") != pins["source_commit"]
        or record.get("binary_sha256") != actual
        or (record.get("origin") == "adopted" and actual not in pins["known_binary_sha256"])
    ):
        raise ParakeetRejected(REASON_UNAVAILABLE)
    return actual


def engine_ready() -> bool:
    try:
        verify_binary()
    except ParakeetRejected:
        return False
    return True


# --- conversion ---------------------------------------------------------------------------------------


def _ms(seconds: object) -> int:
    if isinstance(seconds, bool) or not isinstance(seconds, int | float) or seconds != seconds or abs(seconds) > 1e7:
        raise ParakeetRejected(REASON_INVALID)
    return round(float(seconds) * 1000)


def segments_from_words(words: Sequence[Word]) -> tuple[Segment, ...]:
    """Group words into segments with the engine's own times: a sentence end, a pause or a size cap closes one."""
    segments: list[Segment] = []
    current: list[Word] = []

    def close() -> None:
        if current:
            text = "".join(word.text for word in current).strip()
            segments.append(Segment(text, current[0].start_ms, max(word.end_ms for word in current), tuple(current)))
            current.clear()

    for word in words:
        if current and (
            word.start_ms - current[-1].end_ms >= SEGMENT_GAP_MS
            or word.end_ms - current[0].start_ms > SEGMENT_MAX_MS
            or len(current) >= SEGMENT_MAX_WORDS
        ):
            close()
        current.append(word)
        if word.text.rstrip().endswith((".", "?", "!", "…")):
            close()
    close()
    return tuple(segments)


def parse_output(doc: Mapping[str, Any], audio_ms: int, config: GuardConfig) -> tuple[WordsResult, float | None]:
    """Convert the CLI JSON into contract-v2 words (times in ms on the recording clock).

    Each word keeps its attached punctuation and gets the leading space of the whisper words, because turns are
    built by joining word texts. Times are quantized to 80 ms by the model; word attribution works on the
    overlap with speaker segments, so no finer resolution is assumed. A word that ends before it starts, or
    starts before the previous one, is repaired (and counted); too many of them reject the output.
    """
    raw_words = doc.get("wordTimings")
    if not isinstance(raw_words, list):
        raise ParakeetRejected(REASON_INVALID)
    words: list[Word] = []
    previous_start = previous_end = 0
    broken = out_of_range = 0
    for raw in raw_words:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("word"), str):
            raise ParakeetRejected(REASON_INVALID)
        text = raw["word"].strip()
        if not text:
            continue
        start, end = _ms(raw.get("startTime")), _ms(raw.get("endTime"))
        if start > audio_ms + 1000:
            out_of_range += 1
        repaired = end < start or start < previous_start
        broken += int(repaired)
        if repaired:
            start, end = max(start, previous_start), max(end, start, previous_start)
        start, end, clipped = repair_word_timing(start, end, audio_ms, previous_end)
        repaired = repaired or clipped
        previous_start, previous_end = start, max(previous_end, end)
        confidence = raw.get("confidence")
        probability = (
            float(min(max(confidence, 0.0), 1.0))
            if isinstance(confidence, int | float) and not isinstance(confidence, bool) and confidence == confidence
            else 0.0
        )
        words.append(Word(" " + text, start, end, probability, repaired))
    total = len(words)
    too_broken = broken > config.nonmonotonic_ratio_max * total
    too_far = out_of_range > config.out_of_range_ratio_max * total
    if total and (too_broken or too_far):
        raise ParakeetRejected(REASON_TIMESTAMPS)
    document_confidence = doc.get("confidence")
    confidence_value = (
        float(document_confidence)
        if isinstance(document_confidence, int | float) and not isinstance(document_confidence, bool)
        else None
    )
    segments = segments_from_words(words)
    return WordsResult(segments, sum(word.timing_repaired for word in words)), confidence_value


# --- guard --------------------------------------------------------------------------------------------


def _tokens(words: Sequence[Word]) -> list[str]:
    return [TOKEN_STRIP.sub("", word.text.lower()) for word in words]


def english_rate(words: Sequence[Word]) -> float:
    tokens = _tokens(words)
    return sum(token in ENGLISH_STOPWORDS for token in tokens) / len(tokens) if tokens else 0.0


def has_repetition_loop(tokens: Sequence[str], min_repeats: int) -> bool:
    """A phrase of 1 to 6 words repeated back to back at least ``min_repeats`` times and ``REPEAT_MIN_WORDS`` words."""
    count = len(tokens)
    for period in range(1, 7):
        matches = 0
        for index in range(period, count):
            matches = matches + 1 if tokens[index] == tokens[index - period] and tokens[index] else 0
            if matches >= (min_repeats - 1) * period and matches + period >= REPEAT_MIN_WORDS:
                return True
    return False


def sanity_check(words: WordsResult, language: str, config: GuardConfig) -> tuple[str | None, float]:
    """The reason to reject Parakeet's output (None when it is fine) and the English stopword rate."""
    flat = [word for segment in words.segments for word in segment.words]
    if not flat:
        return REASON_EMPTY, 0.0
    rate = english_rate(flat)
    if language != "en" and len(flat) >= MIN_WORDS_FOR_RATE:
        stopwords = sum(token in ENGLISH_STOPWORDS for token in _tokens(flat))
        if stopwords >= 2 and rate > config.english_rate_max:
            return REASON_DRIFT, rate
    if has_repetition_loop(_tokens(flat), config.repeat_min_repeats):
        return REASON_REPETITION, rate
    return None, rate


# --- subprocess ---------------------------------------------------------------------------------------


def _offline_env() -> dict[str, str]:
    """The inherited environment, with the model registry pointed at a closed port: nothing is ever downloaded."""
    env = dict(os.environ)
    env["REGISTRY_URL"] = env["MODEL_REGISTRY_URL"] = "http://127.0.0.1:9"
    env["HF_HUB_OFFLINE"] = "1"
    return env


def run_cli(wav: Path, output: Path, model_dir: Path, timeout_s: float) -> dict[str, Any]:
    command = [
        str(binary_path()),
        "transcribe",
        str(wav),
        "--model-version",
        "ultra",
        "--word-timestamps",
        "--output-json",
        str(output),
        "--local-model-dir",
        str(model_dir),
    ]
    try:
        run_group(command, check=True, capture_output=True, timeout=timeout_s, env=_offline_env())
    except subprocess.TimeoutExpired:
        logger.error("fluidaudiocli timed out (timeout_s=%d)", round(timeout_s))
        raise ParakeetRejected(REASON_TIMEOUT) from None
    except subprocess.CalledProcessError as exc:
        logger.error("fluidaudiocli failed (exit_code=%s)", exc.returncode)  # stderr may carry paths: not logged
        raise ParakeetRejected(REASON_FAILED) from None
    except OSError:
        raise ParakeetRejected(REASON_UNAVAILABLE) from None
    try:
        document = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ParakeetRejected(REASON_INVALID) from None
    if not isinstance(document, dict):
        raise ParakeetRejected(REASON_INVALID)
    return document


def transcribe(
    wav: Path,
    audio_ms: int,
    language: str,
    model_dir: Path,
    deadline_left_s: float,
    config: GuardConfig | None = None,
) -> ParakeetResult:
    """Transcribe ``wav`` or raise ``ParakeetRejected`` (the request fails with ``failure(reason)``)."""
    config = config or guard_config()
    if language == "auto":
        raise ParakeetRejected(REASON_LANGUAGE_AUTO)  # Parakeet does not detect the language
    if not serves_language(language):
        raise ParakeetRejected(REASON_LANGUAGE_UNSUPPORTED)
    verify_binary()
    cancellation.checkpoint()
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="parakeet-", dir=wav.parent) as temporary:
        document = run_cli(wav, Path(temporary) / "out.json", model_dir, min(deadline_left_s, cli_timeout_s(audio_ms)))
    cli_ms = round((time.monotonic() - started) * 1000)
    words, confidence = parse_output(document, audio_ms, config)
    reason, rate = sanity_check(words, language, config)
    if reason is not None:
        count = sum(len(segment.words) for segment in words.segments)
        logger.warning("Parakeet output rejected (reason=%s, words=%d)", reason, count)
        raise ParakeetRejected(reason)
    rtfx = document.get("rtfx")
    return ParakeetResult(
        words,
        words.segments,
        confidence,
        float(rtfx) if isinstance(rtfx, int | float) and not isinstance(rtfx, bool) else None,
        cli_ms,
        rate,
    )


# --- warm-up ------------------------------------------------------------------------------------------


def _quiet_wav(path: Path, seconds: int = 4) -> None:
    """A short clip of low noise: enough to make Core ML compile the models for the Neural Engine."""
    import random

    rng = random.Random(7)
    samples = b"".join(int(rng.uniform(-300, 300)).to_bytes(2, "little", signed=True) for _ in range(16000 * seconds))
    with wave.open(str(path), "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(16000)
        clip.writeframes(samples)


def warm_key(model_digest: str) -> dict[str, str]:
    return {"binary_sha256": verify_binary(), "model_sha256": model_digest}


def is_warm(model_digest: str) -> bool:
    try:
        return bool(json.loads(warm_marker_path().read_text()).get("key") == warm_key(model_digest))
    except (OSError, ValueError, ParakeetRejected, AttributeError):
        return False


def warm(model_dir: Path, model_digest: str, timeout_s: float = 600.0) -> bool:
    """Run the CLI once on a short clip so the first real recording does not pay for the Core ML compile.

    Records the outcome in ``warm.json`` (keyed by the binary and the model, so a new build warms again).
    Returns True when the run succeeded; never raises for an engine failure.
    """
    try:
        key = warm_key(model_digest)
    except ParakeetRejected:
        return False
    with tempfile.TemporaryDirectory(prefix="parakeet-warm-") as temporary:
        clip = Path(temporary) / "clip.wav"
        _quiet_wav(clip)
        started = time.monotonic()
        try:
            run_cli(clip, Path(temporary) / "out.json", model_dir, timeout_s)
        except ParakeetRejected as error:
            logger.warning("Parakeet warm-up failed (reason=%s)", error.reason)
            return False
    record = {"key": key, "seconds": round(time.monotonic() - started, 1)}
    marker = warm_marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary_marker = marker.with_suffix(".tmp")
    temporary_marker.write_text(json.dumps(record) + "\n")
    temporary_marker.replace(marker)
    logger.info("Parakeet warm-up done (seconds=%s)", record["seconds"])
    return True


__all__ = [
    "BINARY_NAME",
    "CATALOG_ENGINE",
    "DEVICE",
    "ENGINE_NAME",
    "MODEL_ID",
    "GuardConfig",
    "ParakeetRejected",
    "ParakeetResult",
    "default_engine",
    "engine_ready",
    "failure",
    "guard_config",
    "is_warm",
    "serves_language",
    "transcribe",
    "warm",
]


def main(argv: Sequence[str]) -> int:
    """``python -m asr_parakeet --warm``: warm the Core ML cache for the installed model (used by the installer)."""
    from sauri_engine_common.local_model_use import load_runtime_catalog, select_preferred

    logging.basicConfig(level=logging.INFO)
    if list(argv) != ["--warm"]:
        print("usage: python -m asr_parakeet --warm", file=sys.stderr)
        return 2
    selection = select_preferred(process="transcription")
    entry = load_runtime_catalog().get(selection.model_id) if selection is not None else None
    if selection is None or entry is None or entry.sha256 is None:
        print("model_not_installed", file=sys.stderr)
        return 3
    return 0 if warm(selection.path, entry.sha256) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
