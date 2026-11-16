"""The gateway's Parakeet-to-Whisper fallback reaches the provenance of the transcript as a closed reason code."""

from __future__ import annotations

from app.engines.routing import Provenance
from app.transcription.asr_engine import EngineInfo, TranscriptionResult
from app.transcription.worker import _with_local_fallback


def result(**diagnostics: object) -> TranscriptionResult:
    engine = EngineInfo("whisper.cpp", "ggml-large-v3-turbo-q5_0", "metal")
    return TranscriptionResult(engine=engine, diagnostics=diagnostics)


def test_the_reason_the_gateway_reports_becomes_the_fallback_reason() -> None:
    base = Provenance("whisper.cpp", "ggml-large-v3-turbo-q5_0", external=False)
    updated = _with_local_fallback(base, result(engine_fallback_reason="parakeet_language_drift"))
    assert updated.fallback_reason == "parakeet_language_drift"
    assert (updated.engine_name, updated.external) == ("whisper.cpp", False)
    assert updated.engine_model == "ggml-large-v3-turbo-q5_0"


def test_nothing_changes_without_a_reason_or_with_an_unusable_one() -> None:
    base = Provenance("fluidaudio", "parakeet-tdt-0.6b-v3-ultra-coreml", external=False)
    assert _with_local_fallback(base, result()) is base
    for bad in (None, "", 7, "x" * 65):
        assert _with_local_fallback(base, result(engine_fallback_reason=bad)) is base


def test_an_external_provider_failure_keeps_its_own_reason() -> None:
    base = Provenance("whisper.cpp", "m", external=False, fallback_reason="provider_timeout")
    updated = _with_local_fallback(base, result(engine_fallback_reason="parakeet_failed"))
    assert updated.fallback_reason == "provider_timeout"
