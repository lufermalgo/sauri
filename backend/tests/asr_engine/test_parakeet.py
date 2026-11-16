"""The Parakeet backend: JSON to contract v2, the sanity guard, the automatic fallback to whisper.cpp,
default resolution, offline execution and process-group cancellation.

A fake ``fluidaudiocli`` (a Python script driven by ``SAURI_FAKE_MODE``) stands in for the real CLI, and a fake
``whisper-cli`` records the runs of the fallback. The texts are synthetic. The opt-in check with the real
binary and model lives in ``tests/native``.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import nullcontext
from io import BytesIO
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import httpx
import pytest

from tests.local_models_support import BIG, catalog_entry, install_model, route_header, write_catalog

MODULE_PATH = Path(__file__).resolve().parents[2] / "asr-engine" / "native_main.py"
sys.path[:0] = [str(MODULE_PATH.parent), str(MODULE_PATH.parent.parent / "engine-common")]
SPEC = importlib.util.spec_from_file_location("native_asr_engine_parakeet", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
native: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = native
SPEC.loader.exec_module(native)

import asr_parakeet as pk  # noqa: E402
from sauri_engine_common import cancellation  # noqa: E402
from sauri_engine_common.model_bundle import BundleFile, bundle_digest, bundle_size, snapshot  # noqa: E402
from sauri_engine_common.process_group import kill_all  # noqa: E402

PARAKEET_ID = "parakeet-test"
BUNDLE_FILES = {"Encoder.mlmodelc/weights/weight.bin": b"e" * 4096, "config.json": b'{"synthetic": true}'}
BUNDLE = [BundleFile(path, len(data), hashlib.sha256(data).hexdigest()) for path, data in sorted(BUNDLE_FILES.items())]
WHISPER = catalog_entry("asr-big", "transcription", "ggml-big.bin", BIG, default=True, rank=2)
PARAKEET = {
    "id": PARAKEET_ID,
    "process": "transcription",
    "kind": "model",
    "engine": "fluidaudio",
    "repo": "test/repo",
    "revision": "a" * 40,
    "file": "parakeet-dir",
    "size": bundle_size(BUNDLE),
    "sha256": bundle_digest(BUNDLE),
    "files": [{"path": f.path, "size": f.size, "sha256": f.sha256} for f in BUNDLE],
    "min_ram_gib": 4,
    "requires": [],
    "rank": 3,
    "status": "measured",
    "default": False,
    "preferred": True,
    "needs": "fluidaudio-cli",
}
ENGINE = {
    "id": "fluidaudio-cli",
    "process": "transcription",
    "kind": "managed_engine",
    "engine": "fluidaudio",
    "repo": "test/fluid",
    "revision": "b" * 40,
    "managed_by": "scripts/engines/install-parakeet-engine.sh",
    "min_ram_gib": 0,
    "requires": [],
    "rank": 0,
    "status": "measured",
    "default": False,
}

# Synthetic Spanish-like words: no real transcript is involved anywhere in this file.
GOOD = [
    "hola",
    "equipo",
    "vamos",
    "a",
    "revisar",
    "los",
    "objetivos",
    "del",
    "trimestre",
    "con",
    "calma.",
    "luego",
    "pasamos",
    "a",
    "las",
    "cifras",
    "de",
    "ventas,",
    "que",
    "mejoraron",
    "mucho",
    "en",
    "la",
    "region",
    "norte.",
    "despues",
    "vemos",
    "el",
    "plan",
    "de",
    "trabajo",
    "para",
    "el",
    "mes",
    "siguiente",
    "y",
    "los",
    "riesgos",
    "principales",
    "del",
    "proyecto.",
    "al",
    "final",
    "cerramos",
    "con",
    "las",
    "tareas",
    "pendientes",
    "para",
    "cada",
    "persona",
    "del",
    "grupo",
]

FAKE_CLI = """#!{python}
import json, os, sys, time
args = sys.argv[1:]
with open({log!r}, 'a') as log:
    log.write(json.dumps({{"args": args, "registry": os.environ.get("REGISTRY_URL"), "pid": os.getpid()}}) + "\\n")
mode = os.environ.get("SAURI_FAKE_MODE", "ok")
words = json.loads(os.environ.get("SAURI_FAKE_WORDS", "[]"))
if mode == "fail":
    sys.stderr.write("secret transcript text and /private/path")
    sys.exit(2)
if mode == "sleep":
    time.sleep(120)
out = args[args.index("--output-json") + 1]
if mode == "garbage":
    open(out, "w").write("not json")
    sys.exit(0)
timings = []
cursor = 0.4
for index, word in enumerate(words):
    start = cursor
    if mode == "nonmono" and index % 2 == 1:
        start = max(0.0, cursor - 5.0)
    end = max(start, cursor) + 0.16
    timings.append({{"word": word, "startTime": round(start, 2), "endTime": round(end, 2), "confidence": 0.9}})
    cursor = max(cursor, end)
if mode == "empty":
    timings = []
document = {{"text": " ".join(words), "confidence": 0.93, "durationSeconds": 12.0, "rtfx": 150.0}}
document["wordTimings"] = timings
json.dump(document, open(out, "w"))
"""
FAKE_WHISPER = """#!{python}
import json, sys
argv = sys.argv
with open({log!r}, 'a') as log:
    log.write(argv[argv.index('-m') + 1] + '\\n')
document = {{"result": {{"language": "es"}}, "transcription": [{{
    "text": " hola", "offsets": {{"from": 250, "to": 1500}},
    "tokens": [{{"text": " hola", "id": 1, "p": 0.9, "offsets": {{"from": 500, "to": 700}}}}],
}}]}}
with open(argv[argv.index('-of') + 1] + '.json', 'w') as out:
    json.dump(document, out)
"""


class Setup:
    def __init__(self, tmp_path: Path, headers: dict[str, str]) -> None:
        self.tmp = tmp_path
        self.models = tmp_path / "models"
        self.home = tmp_path / "parakeet"
        self.cli_log = tmp_path / "cli.log"
        self.whisper_log = tmp_path / "whisper.log"
        self.legacy = tmp_path / "legacy" / "ggml-large-v3-turbo-q5_0.bin"
        self.headers = headers

    def cli_runs(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.cli_log.read_text().splitlines()] if self.cli_log.exists() else []

    def whisper_runs(self) -> list[str]:
        return self.whisper_log.read_text().splitlines() if self.whisper_log.exists() else []

    def install_parakeet(self, *, provenance: bool = True) -> None:
        directory = self.models / "parakeet-dir"
        for path, data in BUNDLE_FILES.items():
            target = directory / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        record = {
            "id": PARAKEET_ID,
            "sha256": PARAKEET["sha256"],
            "status": "installed",
            "files": snapshot(directory, BUNDLE),
        }
        (self.models / "parakeet-dir.manifest.json").write_text(json.dumps(record))
        cli = self.home / "bin" / "fluidaudiocli"
        cli.parent.mkdir(parents=True, exist_ok=True)
        cli.write_text(FAKE_CLI.format(python=sys.executable, log=str(self.cli_log)))
        cli.chmod(0o755)
        if provenance:
            pins = pk.load_pins()
            (self.home / "provenance.json").write_text(
                json.dumps(
                    {
                        "source_commit": pins["source_commit"],
                        "binary_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
                        "origin": "built",
                    }
                )
            )

    async def transcribe(self, route: str | None, language: str = "es") -> httpx.Response:
        headers = {**self.headers, **({"X-Sauri-Route": route} if route else {})}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url="http://test") as client:
            return await client.post(
                "/transcribe", json={"audio_ref": "synthetic/recording.wav", "language": language}, headers=headers
            )


class SyntheticS3:
    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        return {"Body": BytesIO(b"synthetic audio")}


@pytest.fixture
def setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Setup:
    monkeypatch.setenv("SAURI_ASR_VAD", "off")
    monkeypatch.setenv("SAURI_ASR_SUPPRESS_NST", "off")
    monkeypatch.setenv("SAURI_ASR_VOCABULARY_FILE", str(tmp_path / "absent-vocabulary"))
    token = tmp_path / "engine_token"
    token.write_text("synthetic-token")
    key = tmp_path / "capability_key"
    key.write_bytes(b"synthetic-secret")
    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token)
    monkeypatch.setattr(native, "RECORDING_CAPABILITY_KEY_PATH", key)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "synthetic/")
    monkeypatch.setattr(native, "MINIO_BUCKET", "synthetic-bucket")
    monkeypatch.setattr(native, "s3_client", SyntheticS3())
    monkeypatch.setattr(native, "KeepAwake", nullcontext)
    monkeypatch.setattr(native.tempfile, "tempdir", str(tmp_path))

    def normalize(source: Path, dest: Path, **kwargs: Any) -> Any:
        dest.write_bytes(b"normalized")
        return SimpleNamespace(audio_ms=12_000, seconds=0.01)

    monkeypatch.setattr(native, "normalize_to_wav", normalize)
    expires = int(time.time()) + 60
    signature = hmac.new(b"synthetic-secret", f"synthetic/recording.wav\n{expires}".encode(), hashlib.sha256)
    setup = Setup(tmp_path, {
        "Authorization": "Bearer synthetic-token",
        "X-Sauri-Recording-Capability": f"{expires}.{signature.hexdigest()}",
    })  # fmt: skip
    fake = tmp_path / "whisper-cli"
    fake.write_text(FAKE_WHISPER.format(python=sys.executable, log=str(setup.whisper_log)))
    fake.chmod(0o700)
    setup.legacy.parent.mkdir()
    setup.legacy.write_bytes(BIG)
    monkeypatch.setattr(native, "WHISPER_CLI", str(fake))
    monkeypatch.setattr(native, "ASR_MODEL_PATH", setup.legacy)
    monkeypatch.setenv("SAURI_MODELS_DIR", str(setup.models))
    monkeypatch.setenv("SAURI_PARAKEET_HOME", str(setup.home))
    monkeypatch.setenv("SAURI_FAKE_WORDS", json.dumps(GOOD))
    monkeypatch.setenv(
        "SAURI_MODEL_CATALOG", str(write_catalog(tmp_path / "catalog.json", [WHISPER, PARAKEET, ENGINE]))
    )
    install_model(setup.models, WHISPER, BIG)
    return setup


# --- default resolution ------------------------------------------------------------------------------


async def test_default_is_parakeet_when_installed_and_the_answer_follows_contract_v2(setup: Setup) -> None:
    setup.install_parakeet()
    for route in (
        None,
        route_header("local:default", process="transcription"),
        route_header(f"local:{PARAKEET_ID}", process="transcription"),
    ):
        response = await setup.transcribe(route)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["contract_version"] == 2 and body["language"] == "es"
        assert body["engine"] == {"name": "fluidaudio", "model": PARAKEET_ID, "device": "coreml-ane"}
        words = body["words"]
        assert len(words) == len(GOOD) and all(w["text"].startswith(" ") for w in words)
        assert "".join(w["text"] for w in words).strip() == " ".join(GOOD)
        assert (
            words[0]["start_ms"] == 400 and words[0]["end_ms"] == 560 and words[0]["probability"] == pytest.approx(0.9)
        )
        assert all(
            a["start_ms"] <= a["end_ms"] and a["start_ms"] <= b["start_ms"]
            for a, b in zip(words, words[1:], strict=False)
        )
        assert body["segments"] and all(s["text"] == s["text"].strip() for s in body["segments"])
        assert "engine_fallback_reason" not in body["diagnostics"]
        assert body["diagnostics"]["parakeet"]["rtfx"] == 150.0 and body["diagnostics"]["audio_ms"] == 12_000
    assert setup.whisper_runs() == []


async def test_the_cli_gets_the_managed_model_dir_never_downloads_and_runs_offline(setup: Setup) -> None:
    setup.install_parakeet()
    await setup.transcribe(None)
    (run,) = setup.cli_runs()
    args = run["args"]
    assert (
        args[0] == "transcribe" and "--word-timestamps" in args and args[args.index("--model-version") + 1] == "ultra"
    )
    assert args[args.index("--local-model-dir") + 1] == str(setup.models / "parakeet-dir")
    assert "--model-dir" not in args and "--custom-vocab" not in args and "--encoder-compute-units" not in args
    assert run["registry"] == "http://127.0.0.1:9"


async def test_default_is_whisper_when_parakeet_is_not_installed_and_an_explicit_choice_is_refused(
    setup: Setup,
) -> None:
    response = await setup.transcribe(None)
    assert response.status_code == 200 and response.json()["engine"]["name"] == "whisper.cpp"
    assert "engine_fallback_reason" not in response.json()["diagnostics"] and setup.cli_runs() == []
    refused = await setup.transcribe(route_header(f"local:{PARAKEET_ID}", process="transcription"))
    assert refused.status_code == 409 and refused.json() == {"detail": "model_not_installed"}


async def test_without_the_cli_provenance_the_default_is_whisper(setup: Setup) -> None:
    setup.install_parakeet(provenance=False)
    response = await setup.transcribe(None)
    assert response.json()["engine"]["name"] == "whisper.cpp" and setup.cli_runs() == []


async def test_a_modified_binary_is_not_trusted(setup: Setup) -> None:
    setup.install_parakeet()
    (setup.home / "bin" / "fluidaudiocli").write_text("#!/bin/sh\nexit 0\n")
    (setup.home / "bin" / "fluidaudiocli").chmod(0o755)
    response = await setup.transcribe(None)
    assert response.json()["engine"]["name"] == "whisper.cpp" and setup.cli_runs() == []
    explicit = await setup.transcribe(route_header(f"local:{PARAKEET_ID}", process="transcription"))
    assert explicit.json()["diagnostics"]["engine_fallback_reason"] == pk.REASON_UNAVAILABLE


async def test_the_rollback_switch_and_explicit_whisper_bypass_parakeet(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup.install_parakeet()
    pinned = await setup.transcribe(route_header("local:asr-big", process="transcription"))
    assert pinned.json()["engine"] == {"name": "whisper.cpp", "model": "asr-big", "device": "metal"}
    monkeypatch.setenv("SAURI_ASR_DEFAULT_ENGINE", "whisper")
    rolled_back = await setup.transcribe(None)
    assert rolled_back.json()["engine"]["name"] == "whisper.cpp" and setup.cli_runs() == []
    explicit = await setup.transcribe(route_header(f"local:{PARAKEET_ID}", process="transcription"))
    assert explicit.json()["engine"]["name"] == "fluidaudio"


# --- fallback -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "words", "reason"),
    [
        ("ok", ("the team and that this with you they have what there would " * 6).split(), pk.REASON_DRIFT),
        ("empty", GOOD, pk.REASON_EMPTY),
        ("ok", ["no", "se"] * 20, pk.REASON_REPETITION),
        ("nonmono", GOOD, pk.REASON_TIMESTAMPS),
        ("fail", GOOD, pk.REASON_FAILED),
        ("garbage", GOOD, pk.REASON_INVALID),
    ],
)
async def test_a_rejected_output_is_transcribed_again_with_whisper_and_the_reason_is_recorded(
    setup: Setup,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    mode: str,
    words: list[str],
    reason: str,
) -> None:
    setup.install_parakeet()
    monkeypatch.setenv("SAURI_FAKE_MODE", mode)
    monkeypatch.setenv("SAURI_FAKE_WORDS", json.dumps(words))
    response = await setup.transcribe(None)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"]["name"] == "whisper.cpp" and body["diagnostics"]["engine_fallback_reason"] == reason
    assert len(setup.cli_runs()) == 1 and setup.whisper_runs() == [str(setup.legacy)]
    assert len(reason) <= 64
    assert "secret transcript" not in caplog.text and "/private/path" not in caplog.text


async def test_a_timeout_kills_the_cli_and_falls_back(setup: Setup, monkeypatch: pytest.MonkeyPatch) -> None:
    setup.install_parakeet()
    monkeypatch.setenv("SAURI_FAKE_MODE", "sleep")
    monkeypatch.setenv("SAURI_ASR_PARAKEET_TIMEOUT_S", "1")
    started = time.monotonic()
    response = await setup.transcribe(None)
    assert time.monotonic() - started < 20
    assert response.json()["diagnostics"]["engine_fallback_reason"] == pk.REASON_TIMEOUT
    (run,) = setup.cli_runs()
    assert not _alive(run["pid"])


@pytest.mark.parametrize(
    ("language", "reason"), [("auto", pk.REASON_LANGUAGE_AUTO), ("ja", pk.REASON_LANGUAGE_UNSUPPORTED)]
)
async def test_languages_parakeet_cannot_serve_go_to_whisper_without_running_it(
    setup: Setup, language: str, reason: str
) -> None:
    setup.install_parakeet()
    response = await setup.transcribe(None, language=language)
    assert response.status_code == 200, response.text
    assert response.json()["diagnostics"]["engine_fallback_reason"] == reason and setup.cli_runs() == []


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


# --- cancellation -------------------------------------------------------------------------------------


def test_a_cancelled_job_kills_the_cli_and_its_children(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    setup.install_parakeet()
    monkeypatch.setenv("SAURI_FAKE_MODE", "sleep")
    event = threading.Event()
    token = cancellation.bind(event)
    outcome: list[BaseException] = []

    def work() -> None:
        try:
            pk.run_cli(tmp_path / "in.wav", tmp_path / "out.json", setup.models / "parakeet-dir", timeout_s=60)
        except BaseException as error:  # noqa: BLE001 - the test inspects what ended the run
            outcome.append(error)

    import contextvars

    thread = threading.Thread(target=contextvars.copy_context().run, args=(work,))
    thread.start()
    deadline = time.monotonic() + 10
    while not setup.cli_runs() and time.monotonic() < deadline:
        time.sleep(0.05)
    pid = setup.cli_runs()[0]["pid"]
    assert _alive(pid)
    event.set()
    thread.join(10)
    cancellation.unbind(token)
    assert outcome and isinstance(outcome[0], cancellation.JobCancelled)
    deadline = time.monotonic() + 5
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(pid)


def test_shutdown_kills_a_running_cli(setup: Setup, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    setup.install_parakeet()
    monkeypatch.setenv("SAURI_FAKE_MODE", "sleep")
    thread = threading.Thread(
        target=lambda: _ignore(
            lambda: pk.run_cli(tmp_path / "in.wav", tmp_path / "out.json", setup.models / "parakeet-dir", 60)
        )
    )
    thread.start()
    deadline = time.monotonic() + 10
    while not setup.cli_runs() and time.monotonic() < deadline:
        time.sleep(0.05)
    pid = setup.cli_runs()[0]["pid"]
    kill_all()
    thread.join(10)
    assert not _alive(pid)
    with pytest.raises(ProcessLookupError):
        os.killpg(pid, signal.SIG_DFL)


def _ignore(call: Any) -> None:
    try:
        call()
    except (pk.ParakeetRejected, subprocess.SubprocessError):
        return


# --- pure conversion and guard -----------------------------------------------------------------------


def word(text: str, start: float, end: float, confidence: float = 0.9) -> dict[str, Any]:
    return {"word": text, "startTime": start, "endTime": end, "confidence": confidence}


CONFIG = pk.GuardConfig()


def test_the_json_becomes_words_with_attached_punctuation_ms_times_and_sentence_segments() -> None:
    document = {"wordTimings": [
        word("Hola,", 0.4, 0.56), word("equipo.", 0.56, 0.96),
        word("Vamos", 4.0, 4.32, 1.4), word("ya?", 4.32, 4.56, -2),
        word(" ", 5.0, 5.1),
    ], "confidence": 0.8}  # fmt: skip
    result, confidence = pk.parse_output(document, 10_000, CONFIG)
    flat = [w for s in result.segments for w in s.words]
    assert [w.text for w in flat] == [" Hola,", " equipo.", " Vamos", " ya?"]
    assert [(w.start_ms, w.end_ms) for w in flat] == [(400, 560), (560, 960), (4000, 4320), (4320, 4560)]
    assert [w.probability for w in flat] == [0.9, 0.9, 1.0, 0.0] and confidence == 0.8
    assert [s.text for s in result.segments] == ["Hola, equipo.", "Vamos ya?"]
    assert [(s.start_ms, s.end_ms) for s in result.segments] == [(400, 960), (4000, 4560)]
    assert result.inverted_words == 0


def test_a_long_pause_or_a_long_run_closes_a_segment_without_a_sentence_end() -> None:
    document = {
        "wordTimings": [word("uno", 0.0, 0.2), word("dos", 3.0, 3.2)]
        + [word("w", 3.2 + i * 0.1, 3.3 + i * 0.1) for i in range(100)]
    }
    result, _ = pk.parse_output(document, 60_000, CONFIG)
    assert len(result.segments) == 3 and [len(s.words) for s in result.segments] == [1, 80, 21]


def test_a_few_repaired_words_are_counted_but_many_reject_the_output_and_far_timestamps_too() -> None:
    sane = [word(f"p{i}", i * 0.4, i * 0.4 + 0.3) for i in range(300)]
    sane[100] = word("back", 5.0, 4.0)  # one word that ends before it starts
    result, _ = pk.parse_output({"wordTimings": sane}, 200_000, CONFIG)
    assert result.inverted_words == 1
    assert all(w.start_ms <= w.end_ms for s in result.segments for w in s.words)
    broken = [word(f"p{i}", 10 - (i % 2) * 5 + i, 11 + i) for i in range(300)]
    with pytest.raises(pk.ParakeetRejected) as error:
        pk.parse_output({"wordTimings": broken}, 400_000, CONFIG)
    assert error.value.reason == pk.REASON_TIMESTAMPS
    with pytest.raises(pk.ParakeetRejected) as beyond:
        pk.parse_output({"wordTimings": [word(f"p{i}", 500 + i, 501 + i) for i in range(50)]}, 60_000, CONFIG)
    assert beyond.value.reason == pk.REASON_TIMESTAMPS
    for bad in ({"wordTimings": "x"}, {"wordTimings": [{"word": 3, "startTime": 0, "endTime": 1}]},
                {"wordTimings": [word("a", "x", 1)]}):  # fmt: skip
        with pytest.raises(pk.ParakeetRejected):
            pk.parse_output(bad, 10_000, CONFIG)


def _check(words: list[str], language: str = "es", config: pk.GuardConfig = CONFIG) -> str | None:
    result, _ = pk.parse_output(
        {"wordTimings": [word(w, i * 0.2, i * 0.2 + 0.16) for i, w in enumerate(words)]}, 600_000, config
    )
    return pk.sanity_check(result, language, config)[0]


def test_the_guard_accepts_normal_spanish_and_a_little_english_but_not_a_drift() -> None:
    assert _check(GOOD) is None
    assert (
        _check(GOOD * 4 + ["el", "roadmap", "and", "the", "budget"]) is None
    )  # two English stopwords in 250 words: under 1 %
    assert _check(("the team and that this with you they " * 12).split()) == pk.REASON_DRIFT
    assert _check(("the team and that this with you they " * 12).split(), language="en") is None
    assert _check([]) == pk.REASON_EMPTY
    assert _check(GOOD, config=pk.GuardConfig(english_rate_max=0.0)) is None  # no English stopword: fine at any limit


def test_the_guard_finds_repetition_loops_but_not_ordinary_repeats() -> None:
    assert _check(GOOD + ["no", "se"] * 8) == pk.REASON_REPETITION
    assert _check(GOOD + ["si"] * 12) == pk.REASON_REPETITION
    assert _check(GOOD + ["no", "no", "no", "si", "si", "si", "claro", "claro"] + GOOD) is None
    assert _check(GOOD + ["muy"] * 5 + GOOD) is None
    assert _check(GOOD + ["a", "b", "c"] * 6) == pk.REASON_REPETITION
    assert _check(GOOD + ["a", "b", "c"] * 6, config=pk.GuardConfig(repeat_min_repeats=7)) is None


def test_thresholds_come_from_the_environment_and_invalid_values_fail_at_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert pk.guard_config() == pk.GuardConfig()
    monkeypatch.setenv("SAURI_ASR_PARAKEET_ENGLISH_RATE_MAX", "0.05")
    monkeypatch.setenv("SAURI_ASR_PARAKEET_REPEAT_MIN_REPEATS", "9")
    monkeypatch.setenv("SAURI_ASR_PARAKEET_NONMONOTONIC_MAX_RATIO", "0.02")
    assert pk.guard_config() == pk.GuardConfig(english_rate_max=0.05, repeat_min_repeats=9, nonmonotonic_ratio_max=0.02)
    for name, value in (("SAURI_ASR_PARAKEET_ENGLISH_RATE_MAX", "2"), ("SAURI_ASR_PARAKEET_REPEAT_MIN_REPEATS", "x")):
        monkeypatch.setenv(name, value)
        with pytest.raises(ValueError):
            pk.guard_config()
    monkeypatch.setenv("SAURI_ASR_DEFAULT_ENGINE", "maybe")
    with pytest.raises(ValueError):
        pk.default_engine()


def test_the_cli_timeout_scales_with_the_audio_and_can_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    assert pk.cli_timeout_s(60_000) == pytest.approx(93.0)
    assert pk.cli_timeout_s(3_600_000) == pytest.approx(270.0)
    assert pk.cli_timeout_s(40 * 3_600_000) == 420.0
    monkeypatch.setenv("SAURI_ASR_PARAKEET_TIMEOUT_S", "600")
    assert pk.cli_timeout_s(60_000) == 600.0
    # Parakeet at its limit, then Whisper for an hour of audio, still fits the worker's 1200 s.
    assert 270.0 + 549.0 < 1200.0


def test_the_pins_and_the_quiet_warm_clip(tmp_path: Path) -> None:
    pins = pk.load_pins()
    assert pins["source_commit"] == "16780f04d2ece24f67d0fc00efccd0296491c1a8"
    clip = tmp_path / "clip.wav"
    pk._quiet_wav(clip)
    import wave

    with wave.open(str(clip), "rb") as reader:
        assert (reader.getnchannels(), reader.getsampwidth(), reader.getframerate(), reader.getnframes()) == (
            1,
            2,
            16000,
            64000,
        )


def test_warm_runs_the_cli_once_and_is_remembered_per_binary_and_model(setup: Setup) -> None:
    setup.install_parakeet()
    model_dir = setup.models / "parakeet-dir"
    assert not pk.is_warm(PARAKEET["sha256"])
    assert pk.warm(model_dir, PARAKEET["sha256"], timeout_s=30)
    assert pk.is_warm(PARAKEET["sha256"]) and not pk.is_warm("f" * 64)
    assert len(setup.cli_runs()) == 1
