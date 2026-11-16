"""Recommendation: determinism, monotonicity (Property 9) and the documented decision table."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st
from sauri_engine_common.recommend import HardwareProfile, load_catalog, recommend

CATALOG = load_catalog()
RANK = {model.id: model.rank for model in CATALOG.models}
MIN_RAM = {model.id: model.min_ram_gib for model in CATALOG.models}


def hardware(memory_gib: float, arch: str = "arm64", macos_major: int = 26) -> HardwareProfile:
    return HardwareProfile(
        arch=arch, memory_gib=memory_gib, cores=8, metal=arch == "arm64", system="Darwin", macos_major=macos_major,
    )


def ids(profile: HardwareProfile) -> dict[str, str | None]:
    return {process: rec.model_id for process, rec in recommend(profile, CATALOG).items()}


def test_8_gib_apple_silicon() -> None:
    result = recommend(hardware(8), CATALOG)
    assert ids(hardware(8)) == {
        "transcription": "parakeet-tdt-0.6b-v3-ultra-coreml",
        "summary": "qwen3.5-4b-q4_k_m",
        "diarization": "senko-coreml",
    }
    assert result["transcription"].reason_key == "fits" and result["transcription"].status == "measured"
    summary = result["summary"]
    assert summary.reason_key == "reduced" and summary.status == "proposal"
    assert summary.reason_params["better_id"] == "qwen3.5-9b-q4_k_m" and summary.reason_params["limited_by"] == "memory"
    assert set(summary.warnings) == {"unmeasured_proposal", "lower_quality_expected", "suggest_external_provider"}


def test_an_older_macos_gets_whisper_and_is_not_told_it_is_reduced() -> None:
    result = recommend(hardware(16, macos_major=13), CATALOG)["transcription"]
    assert result.model_id == "whisper-large-v3-turbo-q5_0" and result.reason_key == "fits"
    assert "lower_quality_expected" not in result.warnings
    assert recommend(hardware(16, macos_major=0), CATALOG)["transcription"].model_id == "whisper-large-v3-turbo-q5_0"


def test_the_engine_a_model_needs_is_never_recommended_on_its_own() -> None:
    assert "fluidaudio-cli" not in {rec.model_id for rec in recommend(hardware(16), CATALOG).values()}


def test_16_and_24_gib_apple_silicon() -> None:
    for memory in (16, 24):
        result = recommend(hardware(memory), CATALOG)
        assert ids(hardware(memory))["summary"] == "qwen3.5-9b-q4_k_m"
        assert result["summary"].reason_key == "fits" and result["summary"].warnings == ()
        assert result["summary"].reason_params == {"memory_gib": memory, "min_ram_gib": 16}
    assert ids(hardware(16)) == ids(hardware(24))


def test_below_8_gib_there_is_no_local_summary_model() -> None:
    summary = recommend(hardware(4), CATALOG)["summary"]
    assert summary.model_id is None and summary.status is None and summary.reason_key == "no_local_model"
    assert summary.reason_params["needs"] == "memory" and "suggest_external_provider" in summary.warnings
    assert ids(hardware(4))["transcription"] == "whisper-small-q5_1"


def test_without_metal_transcription_falls_back_and_diarization_has_no_model() -> None:
    result = recommend(hardware(16, arch="x86_64"), CATALOG)
    assert result["transcription"].model_id == "whisper-small-q5_1"
    assert "no_metal_slow" in result["transcription"].warnings
    assert result["transcription"].reason_params["limited_by"] == "metal"
    assert result["diarization"].model_id is None and result["diarization"].reason_params["needs"] == "metal"


def test_the_auxiliary_vad_is_never_recommended() -> None:
    for memory in (2, 8, 64):
        assert "silero-vad-v6.2.0" not in ids(hardware(memory)).values()


def test_the_result_is_serializable_and_deterministic() -> None:
    first = {k: v.as_dict() for k, v in recommend(hardware(8), CATALOG).items()}
    assert first == {k: v.as_dict() for k, v in recommend(hardware(8), CATALOG).items()}
    assert first["summary"]["reason_params"]["memory_gib"] == 8


memory_values = st.floats(min_value=0, max_value=512, allow_nan=False)
archs = st.sampled_from(["arm64", "x86_64"])


@given(low=memory_values, high=memory_values, arch=archs)
def test_more_memory_never_lowers_the_recommended_level(low: float, high: float, arch: str) -> None:
    """Property 9: monotone with memory, and never a model whose minimum exceeds the memory."""
    low, high = min(low, high), max(low, high)
    before, after = recommend(hardware(low, arch), CATALOG), recommend(hardware(high, arch), CATALOG)
    for process in before:
        old, new = before[process].model_id, after[process].model_id
        assert (RANK[new] if new else -1) >= (RANK[old] if old else -1)
        if new:
            assert MIN_RAM[new] <= high
        if old:
            assert MIN_RAM[old] <= low
