"""Load the standalone host service without installing it in the API."""

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND / "engine-common"))
sys.path.insert(0, str(BACKEND / "host-engine"))

MANAGEMENT_TOKEN = "synthetic-management-token-0123456789"
ENGINE_TOKEN = "synthetic-engine-token-abcdefghijk"


def load_host_module(token_file: Path, secrets_dir: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("sauri_test_host_native", BACKEND / "host-engine" / "native_main.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from sauri_engine_common.secrets import FileSecretStore

    module.ADOPT_ON_START = False  # tests never adopt (or hash) files outside their own temp directories
    module.MANAGEMENT_TOKEN_PATH = token_file
    module._store = FileSecretStore(secrets_dir)
    return module


@pytest.fixture
def host(tmp_path: Path) -> Iterator[ModuleType]:
    token_file = tmp_path / "management_token"
    token_file.write_text(MANAGEMENT_TOKEN + "\n")
    token_file.chmod(0o600)
    module = load_host_module(token_file, tmp_path / "secrets")
    module.secrets_dir = tmp_path / "secrets"
    yield module


@pytest.fixture(autouse=True)
def _no_real_model_locations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every location the host service could read at an empty temp directory, never at the owner's files."""
    monkeypatch.setenv("SAURI_MODELS_DIR", str(tmp_path / "env-models"))
    monkeypatch.setenv("SAURI_LLM_MODEL_FILE", str(tmp_path / "env-legacy" / "llm.gguf"))
    monkeypatch.setenv("ASR_MODEL_PATH", str(tmp_path / "env-legacy" / "asr.bin"))
    monkeypatch.setenv("SAURI_DIAR_VENV", str(tmp_path / "env-diar-venv"))
