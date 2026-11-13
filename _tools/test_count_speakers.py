"""Contract tests only. These do not establish acoustic accuracy."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import count_speakers as counter  # noqa: E402


def test_count_is_labels_not_turns() -> None:
    class Annotation:
        def labels(self) -> list[str]:
            return ["A", "B", "C"]

    assert counter.count_labels(Annotation()) == 3


def test_empty_annotation() -> None:
    class Annotation:
        def labels(self) -> list[str]:
            return []

    assert counter.count_labels(Annotation()) == 0


@pytest.mark.parametrize("value", ["nan", "inf", "-0.1", "2.1"])
def test_invalid_threshold(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        counter.threshold_value(value)


@pytest.mark.parametrize("value", ["0", "0.7045654963945799", "0.8", "2"])
def test_valid_threshold(value: str) -> None:
    assert counter.threshold_value(value) == float(value)


def test_only_threshold_changes_without_mutating_defaults() -> None:
    defaults: dict[str, Any] = {
        "clustering": {"threshold": 0.7045654963945799, "method": "centroid", "min_cluster_size": 12},
        "segmentation": {"min_duration_off": 0.0},
    }
    assert counter.configured_parameters(defaults, None) == defaults
    adjusted = counter.configured_parameters(defaults, 0.8)
    assert adjusted["clustering"].pop("threshold") == 0.8
    original = counter.configured_parameters(defaults, None)
    assert original["clustering"].pop("threshold") == 0.7045654963945799
    assert adjusted == original
    assert defaults["clustering"]["threshold"] == 0.7045654963945799


def test_no_speaker_count_or_cpu_options() -> None:
    options = {option for action in counter.parser()._actions for option in action.option_strings}
    assert not options.intersection({"--num-speakers", "--min-speakers", "--max-speakers", "--device"})


@pytest.mark.parametrize("value", ["0", "-1"])
def test_invalid_batch_size(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        counter.positive_batch_size(value)


def test_batch_override_preserves_other_configuration() -> None:
    pipeline = SimpleNamespace(segmentation_batch_size=32, embedding_batch_size=32,
                               clustering={"method": "centroid", "threshold": 0.7045654963945799})
    counter.apply_batch_sizes(pipeline, None, None)
    assert pipeline.segmentation_batch_size == pipeline.embedding_batch_size == 32
    counter.apply_batch_sizes(pipeline, 4, 4)
    assert pipeline.segmentation_batch_size == pipeline.embedding_batch_size == 4
    assert pipeline.clustering == {"method": "centroid", "threshold": 0.7045654963945799}
    assert counter.positive_batch_size("1") == 1
    counter.apply_batch_sizes(pipeline, 1, None)
    assert pipeline.segmentation_batch_size == 1 and pipeline.embedding_batch_size == 4
    counter.apply_batch_sizes(pipeline, None, 2)
    assert pipeline.segmentation_batch_size == 1 and pipeline.embedding_batch_size == 2


@pytest.mark.parametrize("value", ["0", "-1", "abc", "1.5"])
def test_cli_rejects_invalid_batch_sizes(value: str) -> None:
    with pytest.raises(SystemExit):
        counter.parser().parse_args(["input.webm", "--cache", "cache", "--scratch", "scratch",
                                     "--output-dir", "results", f"--segmentation-batch-size={value}"])


def test_cli_batch_defaults_and_overrides() -> None:
    base = ["input.webm", "--cache", "cache", "--scratch", "scratch", "--output-dir", "results"]
    defaults = counter.parser().parse_args(base)
    assert defaults.segmentation_batch_size is None and defaults.embedding_batch_size is None
    adjusted = counter.parser().parse_args(base + ["--segmentation-batch-size", "4",
                                                  "--embedding-batch-size", "4"])
    assert adjusted.segmentation_batch_size == adjusted.embedding_batch_size == 4
    assert adjusted.clustering_threshold is None


def test_memory_pressure_must_be_sustained(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    monkeypatch.setattr(counter, "resource_sample", lambda: {
        "memory_pressure_level": 2, "active_competitor_pids": [],
    })
    guard = counter.ResourceGuard()
    guard.check()
    now[0] = 20
    guard.check()
    now[0] = 31
    with pytest.raises(RuntimeError, match="memory warning"):
        guard.check()


def test_only_unused_mps_pool_is_released(monkeypatch: pytest.MonkeyPatch) -> None:
    released = []
    mps = SimpleNamespace(driver_allocated_memory=lambda: 200, current_allocated_memory=lambda: 100,
                          synchronize=lambda: released.append("synchronize"),
                          empty_cache=lambda: released.append("release"))
    torch = SimpleNamespace(backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True)), mps=mps)
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setattr(counter, "resource_sample", lambda: {
        "memory_pressure_level": 1, "active_competitor_pids": [],
    })
    guard = counter.ResourceGuard()
    guard.check(initial=True)
    assert released == ["synchronize", "release"]
    assert guard.events[0]["mps_live_tensor_bytes"] == 100
    assert guard.events[0]["mps_driver_bytes"] == 200


def test_competing_inference_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(counter, "resource_sample", lambda: {
        "memory_pressure_level": 1, "active_competitor_pids": [123],
    })
    with pytest.raises(RuntimeError, match="PIDs \\[123\\]"):
        counter.ResourceGuard().check(initial=True)


def test_error_manifest_and_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audio, cache = tmp_path / "input.webm", tmp_path / "cache"
    audio.write_bytes(b"synthetic fixture, not acoustic validation")
    cache.mkdir()
    monkeypatch.setattr(counter, "resource_sample", lambda: {
        "memory_pressure_level": 1, "active_competitor_pids": [],
    })

    def fail(_args: Any, work: Path, _result: Any, _guard: Any) -> int:
        (work / "decoded.wav").write_bytes(b"temporary")
        raise RuntimeError("test failure")

    monkeypatch.setattr(counter, "infer", fail)
    assert counter.main([str(audio), "--cache", str(cache), "--scratch", str(tmp_path),
                         "--output-dir", str(tmp_path / "results")]) == 1
    results = list((tmp_path / "results").glob("*/result.json"))
    result = json.loads(results[0].read_text())
    assert result["error"] == {"type": "RuntimeError", "message": "test failure"}
    assert result["input_unchanged"] and result["cache_unchanged"]
    assert result["temporary_directory_cleaned"]
    assert not list(tmp_path.glob("speaker-count-*"))


def test_progress_accepts_numpy_scalar_counts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    class ScalarCount:
        def __int__(self) -> int:
            return 100

    monkeypatch.setattr(counter.ResourceGuard, "check", lambda _self: None)
    counter.ResourceGuard().hook("segmentation", None, completed=ScalarCount(), total=ScalarCount())
    progress = json.loads(capsys.readouterr().err)
    assert progress["completed"] == progress["total"] == 100


def test_socket_connections_denied() -> None:
    with pytest.raises(RuntimeError, match="Network disabled"):
        counter.deny_network()


def test_no_production_imports() -> None:
    spec = importlib.util.find_spec("count_speakers")
    assert spec is not None and spec.origin is not None
    source = Path(spec.origin).read_text()
    assert "num_speakers=" not in source
    assert "min_speakers=" not in source
    assert "max_speakers=" not in source
    assert "from app" not in source
