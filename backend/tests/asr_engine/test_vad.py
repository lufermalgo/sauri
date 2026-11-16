"""VAD chunking and engine flow with synthetic PCM and simulated subprocesses."""

from __future__ import annotations

import importlib
import json
import subprocess
import time
import wave
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import given
from hypothesis import strategies as st
from test_native_contract import native

vad = importlib.import_module("asr_vad")
config = importlib.import_module("asr_config")


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    for name in ("SAURI_ASR_VAD", "SAURI_ASR_VAD_THRESHOLD", "SAURI_ASR_CHUNK_SECONDS", "SAURI_ASR_SUPPRESS_NST"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SAURI_ASR_VOCABULARY_FILE", str(tmp_path / "absent"))
    def unexpected(*args, **kwargs):
        pytest.fail("Real subprocesses are forbidden in VAD tests")
    monkeypatch.setattr(native.subprocess, "run", unexpected)


def write_wav(path, frames=160000, data=None):
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        output.writeframes(data if data is not None else b"\x01\x00" * frames)


def document(text=" alpha", language="es", start=100, end=500):
    return {"result": {"language": language}, "transcription": [{
        "text": text, "offsets": {"from": start, "to": end},
        "tokens": [{"text": text, "id": 1, "p": 0.9, "offsets": {"from": start, "to": end}}],
    }]}


def simulate(monkeypatch, documents, stdout=None, fail_at=None, tick=None):
    commands = []
    if stdout is None:
        stdout = ("Detected 2 speech segments:\n"
                  "Speech segment 0: start = 100.00, end = 200.00\n"
                  "Speech segment 1: start = 800.00, end = 900.00\n")
    def run(command, **kwargs):
        commands.append((command, kwargs))
        assert kwargs["timeout"] > 0 and kwargs["check"] and kwargs["capture_output"]
        if tick:
            tick()
        if "-vm" in command:
            assert "-vt" in command and kwargs["text"]
            return SimpleNamespace(stdout=stdout)
        index = sum("-vm" not in cmd for cmd, _ in commands) - 1
        assert "--vad" not in command
        if fail_at == index:
            raise subprocess.CalledProcessError(19, command, stderr=b"private content")
        with wave.open(command[command.index("-f") + 1], "rb") as audio:
            assert audio.getnframes() == 1600 * 16
        Path(command[-1] + ".json").write_text(json.dumps(documents[index]))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(native.subprocess, "run", run)
    return commands


def test_parser_ignores_noise_and_converts_centiseconds():
    output = """ggml_metal: setup
Detected GPU device: synthetic
Detected 2 speech segments:
Speech segment 0: start = 6893.00, end = 7107.00
load_backend: loaded CPU
Speech segment 1: start = 7200.15, end = 7400.00
whisper_vad: complete
"""
    assert vad.parse_vad(output, 73500) == [(68930, 71070), (72002, 73500)]
    assert vad.parse_vad("noise\nDetected 0 speech segments:\nnoise", 1000) == []


@pytest.mark.parametrize("output", [
    "noise only", "Detected 1 speech segments:", "Detected 0 speech segments:\nDetected 0 speech segments:",
    "Detected 1 speech segments:\nSpeech segment 0: start = NaN, end = 10.00",
    "Detected 1 speech segments:\nSpeech segment 1: start = 0.00, end = 10.00",
    "Detected 1 speech segments:\nSpeech segment 0: start = 20.00, end = 10.00",
    "Detected 1 speech segments:\nSpeech segment 0: start = 2000.00, end = 2100.00",
    "Detected 2 speech segments:\nSpeech segment 0: start = 0, end = 100\n"
    "Speech segment 1: start = 50, end = 150",
])
def test_parser_fails_closed_on_incomplete_or_invalid_output(output):
    with pytest.raises(ValueError):
        vad.parse_vad(output, 10000)


def test_groups_silence_threshold_and_clips_padding():
    assert vad.group_chunks([(100, 1000), (5000, 6000), (10001, 11000)], 11100, 120000) == [
        (0, 6300), (9701, 11100),
    ]
    assert vad.group_chunks([], 1000, 120000) == []


def test_splits_at_largest_gap_not_greedily_at_size_boundary():
    assert vad.group_chunks([(1000, 3000), (4000, 5000), (8000, 9000), (10000, 12000)], 15000, 8000) == [
        (700, 5300), (7700, 12300),
    ]


def test_single_long_interval_is_not_cut_and_padding_counts_towards_limit():
    assert vad.group_chunks([(1000, 10000)], 11000, 4000) == [(700, 10300)]
    assert vad.group_chunks([(1000, 4900)], 10000, 4000) == [(900, 4900)]
    assert vad.group_chunks([(0, 1000)], 1100, 2000) == [(0, 1100)]


def test_overlap_padding_shares_boundary_in_gap_without_cutting_voice():
    assert vad.group_chunks([(1000, 3000), (3100, 5100)], 6000, 3000) == [(700, 3000), (3000, 5400)]


@given(st.lists(st.tuples(st.integers(0, 6000), st.integers(1, 4000)), min_size=1, max_size=60))
def test_group_properties_keep_every_speech_interval_without_overlapping_chunks(parts):
    intervals = []
    cursor = 0
    for gap, duration in parts:
        intervals.append((cursor + gap, cursor + gap + duration))
        cursor += gap + duration
    chunks = vad.group_chunks(intervals, cursor + 100, 5000)
    assert all(0 <= start < end <= cursor + 100 and end - start <= 5000 for start, end in chunks)
    assert all(left[1] <= right[0] for left, right in zip(chunks, chunks[1:], strict=False))
    for start, end in intervals:
        assert sum(a <= start and end <= b for a, b in chunks) == 1
    for a, b in chunks:
        contained = [(start, end) for start, end in intervals if a <= start and end <= b]
        assert all(b[0] - a[1] <= 4000 for a, b in zip(contained, contained[1:], strict=False))


def test_cut_wav_uses_original_samples_and_handles_rounded_last_ms(tmp_path):
    source, target = tmp_path / "audio.wav", tmp_path / "cut.wav"
    samples = b"".join(i.to_bytes(2, "little", signed=True) for i in range(16009))
    write_wav(source, 16009, samples)
    vad.cut_wav(source, target, (500, 1001), time.monotonic() + 10)
    with wave.open(str(target), "rb") as audio:
        assert audio.getnframes() == 8009
        assert audio.readframes(8009) == samples[8000 * 2:]
    with pytest.raises(TimeoutError):
        vad.cut_wav(source, target, (0, 500), time.monotonic() - 1)
    with pytest.raises(ValueError):
        vad.cut_wav(source, target, (0, 1002), time.monotonic() + 10)


def test_alignment_adds_offset_and_clips_overlap_without_losing_words():
    first = native.words_from_ggml_json(document(" alpha", start=10, end=1000), 1000)
    second = native.words_from_ggml_json(document(" beta", start=0, end=400), 1000)
    merged = vad.align_chunks([((5000, 6000), first), ((5800, 6800), second)])
    assert [(s.start_ms, s.end_ms) for s in merged.segments] == [(5010, 5800), (5800, 6200)]
    words = [word for segment in merged.segments for word in segment.words]
    assert [(w.start_ms, w.end_ms) for w in words] == [(5010, 5800), (5800, 6200)]
    assert [w.text for w in words] == [" alpha", " beta"]
    assert words[0].timing_repaired and not words[1].timing_repaired


def test_alignment_repairs_regressing_decoder_times_by_clipping():
    doc = document(start=300, end=900)
    doc["transcription"] += document(" beta", start=100, end=500)["transcription"]
    merged = vad.align_chunks([((1000, 2000), native.words_from_ggml_json(doc, 1000))])
    words = [word for segment in merged.segments for word in segment.words]
    assert [(w.start_ms, w.end_ms) for w in words] == [(1100, 1100), (1100, 1500)]
    assert words[0].timing_repaired


@pytest.mark.parametrize("requested,expected", [("auto", ["auto", "es"]), ("en", ["en", "en"])])
def test_engine_flow_uses_global_clock_single_language_and_content_free_diagnostics(monkeypatch, tmp_path,
                                                                                  requested, expected):
    source = tmp_path / "audio.wav"
    write_wav(source)
    commands = simulate(monkeypatch, [document(), document(" beta", language="fr")])
    monkeypatch.setenv("SAURI_ASR_VAD_THRESHOLD", "0.6")
    result, language, diagnostics, inference_ms = native._transcribe_wav(
        source, 10000, requested, time.monotonic() + 30,
    )
    assert language == "es"
    assert [cmd[cmd.index("-l") + 1] for cmd, _ in commands if "-l" in cmd] == expected
    assert commands[0][0][-1] == "0.6"
    assert [(s.start_ms, s.end_ms) for s in result.segments] == [(800, 1200), (7800, 8200)]
    assert diagnostics == {"enabled": True, "speech_segments": 2, "chunks": 2, "speech_ms": 2000,
                           "skipped_ms": 6800, "vad_ms": diagnostics["vad_ms"], "inference_ms": inference_ms}
    assert "alpha" not in json.dumps(diagnostics) and "beta" not in json.dumps(diagnostics)
    assert list(tmp_path.iterdir()) == [source]


def test_first_chunk_without_words_does_not_choose_language(monkeypatch, tmp_path):
    source = tmp_path / "audio.wav"
    write_wav(source)
    empty = {"transcription": [], "result": {"language": "fr"}}
    commands = simulate(monkeypatch, [empty, document()])
    _, language, diagnostics, _ = native._transcribe_wav(source, 10000, "auto", time.monotonic() + 30)
    assert language == "es" and diagnostics["chunks"] == 2
    assert [cmd[cmd.index("-l") + 1] for cmd, _ in commands if "-l" in cmd] == ["auto", "auto"]


@pytest.mark.parametrize("fail_at", [0, 1])
def test_failing_chunk_discards_job_and_cleans_chunk_files(monkeypatch, tmp_path, fail_at, caplog):
    source = tmp_path / "audio.wav"
    write_wav(source)
    simulate(monkeypatch, [document(), document()], fail_at=fail_at)
    with pytest.raises(subprocess.CalledProcessError):
        native._transcribe_wav(source, 10000, "es", time.monotonic() + 30)
    assert "private content" not in caplog.text
    assert "exit_code=19" in caplog.text
    assert list(tmp_path.iterdir()) == [source]


@pytest.mark.parametrize(("empty_vad", "detail", "status"), [
    (False, "no_word_timestamps", 500), (True, "no_speech", 422),
])
def test_no_voice_is_a_distinct_client_result_and_no_decoded_words_keeps_the_controlled_error(
    monkeypatch, tmp_path, caplog, empty_vad, detail, status,
):
    source = tmp_path / "source.wav"
    source.write_bytes(b"synthetic source")
    monkeypatch.setattr(native, "_download_audio", lambda *args: str(source))
    monkeypatch.setattr(native, "KeepAwake", nullcontext)
    monkeypatch.setattr(native.tempfile, "tempdir", str(tmp_path))
    def normalize(source, target, **kwargs):
        write_wav(target)
        return SimpleNamespace(audio_ms=10000, seconds=0)
    monkeypatch.setattr(native, "normalize_to_wav", normalize)
    commands = simulate(monkeypatch, [{"transcription": []}, {"transcription": []}],
                        stdout="Detected 0 speech segments:" if empty_vad else None)
    with caplog.at_level("INFO", logger=native.logger.name), pytest.raises(native.HTTPException) as exc:
        native._transcribe_audio(native.TranscribeRequest(audio_ref="synthetic.wav"), time.monotonic() + 30)
    assert exc.value.status_code == status and exc.value.detail == detail
    assert len(commands) == (1 if empty_vad else 3)
    assert not list(tmp_path.iterdir())
    no_speech_lines = [record for record in caplog.records if "no speech" in record.getMessage()]
    assert len(no_speech_lines) == (1 if empty_vad else 0)
    assert str(tmp_path) not in caplog.text and "synthetic" not in caplog.text


def test_shared_deadline_and_sum_of_inference_times(monkeypatch, tmp_path):
    source = tmp_path / "audio.wav"
    write_wav(source)
    clock = [100.0]
    monkeypatch.setattr(native.time, "monotonic", lambda: clock[0])
    commands = simulate(monkeypatch, [document(), document()], tick=lambda: clock.__setitem__(0, clock[0] + 2))
    _, _, diagnostics, inference_ms = native._transcribe_wav(source, 10000, "es", 110)
    assert [kw["timeout"] for _, kw in commands] == [10, 8, 6]
    assert diagnostics["vad_ms"] == 2000 and inference_ms == diagnostics["inference_ms"] == 4000


def test_expired_deadline_never_starts_next_chunk(monkeypatch, tmp_path):
    source = tmp_path / "audio.wav"
    write_wav(source)
    clock = [100.0]
    monkeypatch.setattr(native.time, "monotonic", lambda: clock[0])
    commands = simulate(monkeypatch, [document()], tick=lambda: clock.__setitem__(0, clock[0] + 2))
    with pytest.raises(TimeoutError):
        native._transcribe_wav(source, 10000, "es", 103)
    assert len(commands) == 2 and list(tmp_path.iterdir()) == [source]


@pytest.mark.parametrize("setting,flag", [("off", False), ("on", True)])
def test_suppress_nst_is_explicit_and_off_by_default(monkeypatch, tmp_path, setting, flag):
    assert config.suppress_nst() is False
    monkeypatch.setenv("SAURI_ASR_SUPPRESS_NST", setting)
    def run(command, **kwargs):
        assert ("-sns" in command) is flag
        Path(command[-1] + ".json").write_text(json.dumps(document()))
    monkeypatch.setattr(native.subprocess, "run", run)
    native._run_whisper(tmp_path / "audio.wav", tmp_path / "out", "es", 10)


@pytest.mark.parametrize("variable,value,function", [
    ("SAURI_ASR_VAD", "invalid", config.vad_enabled),
    ("SAURI_ASR_VAD_THRESHOLD", "nan", config.vad_threshold),
    ("SAURI_ASR_VAD_THRESHOLD", "1.1", config.vad_threshold),
    ("SAURI_ASR_CHUNK_SECONDS", "0", config.chunk_ms),
    ("SAURI_ASR_CHUNK_SECONDS", "inf", config.chunk_ms),
    ("SAURI_ASR_CHUNK_SECONDS", "1e308", config.chunk_ms),
    ("SAURI_ASR_SUPPRESS_NST", "maybe", config.suppress_nst),
])
def test_invalid_configuration_fails_closed(monkeypatch, variable, value, function):
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValueError):
        function()


def test_configuration_defaults():
    assert config.vad_enabled() is True
    assert config.vad_threshold() == 0.5
    assert config.chunk_ms() == 120000
    assert config.suppress_nst() is False


@pytest.mark.parametrize("threshold", ["0", "1"])
def test_threshold_accepts_endpoints(monkeypatch, threshold):
    monkeypatch.setenv("SAURI_ASR_VAD_THRESHOLD", threshold)
    assert config.vad_threshold() == float(threshold)


def test_each_chunk_receives_vocabulary_and_an_independent_audio_file(monkeypatch, tmp_path):
    source = tmp_path / "audio.wav"
    write_wav(source)
    vocabulary = tmp_path / "vocabulary.txt"
    vocabulary.write_text("Zorvex\nVeltra\n")
    monkeypatch.setenv("SAURI_ASR_VOCABULARY_FILE", str(vocabulary))
    commands = simulate(monkeypatch, [document(), document()])
    native._transcribe_wav(source, 10000, "es", time.monotonic() + 30)
    asr = [cmd for cmd, _ in commands if "-vm" not in cmd]
    assert len({cmd[cmd.index("-f") + 1] for cmd in asr}) == 2
    for cmd in asr:
        assert cmd[cmd.index("--prompt") + 1] == native.vocabulary_prompt(vocabulary)
        assert "--carry-initial-prompt" in cmd and "-sns" not in cmd
        assert cmd[cmd.index("-bs") + 1] == "5" and cmd[cmd.index("-bo") + 1] == "5" and "-fa" in cmd


@pytest.mark.parametrize("failure", [None, "chunk", "vad", "malformed"])
def test_vad_response_preserves_full_duration_and_never_returns_partial_results(monkeypatch, tmp_path, failure, caplog):
    source = tmp_path / "source.wav"
    source.write_bytes(b"synthetic source")
    monkeypatch.setattr(native, "_download_audio", lambda *args: str(source))
    monkeypatch.setattr(native, "KeepAwake", nullcontext)
    monkeypatch.setattr(native.tempfile, "tempdir", str(tmp_path))
    def normalize(source, target, **kwargs):
        write_wav(target)
        return SimpleNamespace(audio_ms=10000, seconds=0.01)
    monkeypatch.setattr(native, "normalize_to_wav", normalize)
    simulate(monkeypatch, [document(), document()], fail_at=1 if failure == "chunk" else None,
             stdout="private unexpected output" if failure == "malformed" else None)
    if failure == "vad":
        def fail(command, **kwargs):
            assert "-vm" in command
            raise subprocess.CalledProcessError(3, command, stderr="private output /Users/private/audio.wav")
        monkeypatch.setattr(native.subprocess, "run", fail)
    request = native.TranscribeRequest(audio_ref="synthetic.wav")
    if failure:
        with pytest.raises(native.HTTPException) as exc:
            native._transcribe_audio(request, time.monotonic() + 30)
        assert exc.value.status_code == 500 and exc.value.detail == "engine_failed"
        assert "private" not in caplog.text
    else:
        response = native._transcribe_audio(request, time.monotonic() + 30)
        assert response.diagnostics["audio_ms"] == 10000
        assert response.diagnostics["vad"]["chunks"] == 2
        assert response.contract_version == 2
        assert len(response.words) == len(response.segments) == 2
        assert response.words[1].start_ms == 7800
    assert list(tmp_path.iterdir()) == []
