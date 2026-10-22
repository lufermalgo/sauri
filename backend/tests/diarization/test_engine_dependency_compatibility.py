"""Regression test for the diarization engine's runtime dependency compatibility."""

from pathlib import Path


def test_pyannote_engine_uses_compatible_runtime_dependencies() -> None:
    """Pin audio and Hub APIs used by pyannote.audio 3.3.2."""
    requirements_path = Path(__file__).resolve().parents[2] / "diar-engine" / "requirements.txt"
    requirements = requirements_path.read_text(encoding="utf-8").splitlines()

    assert "torch==2.5.1" in requirements
    assert "torchaudio==2.5.1" in requirements
    assert "huggingface_hub<1.0.0" in requirements
    assert "matplotlib>=3.7.0" in requirements
    assert "--extra-index-url https://download.pytorch.org/whl/cpu" in requirements
