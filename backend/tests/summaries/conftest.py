"""Summary tests must never read the developer's real engine credential."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def synthetic_engine_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    token = tmp_path / "engine-token"
    token.write_text("synthetic-local-engine-token")
    monkeypatch.setenv("SAURI_ENGINE_TOKEN_FILE", str(token))
    monkeypatch.delenv("SUMMARIZATION_API_KEY_FILE", raising=False)
