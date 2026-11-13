"""Contract tests only. These do not establish acoustic accuracy."""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import os
import resource
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
                          empty_cache=lambda: released.append("release"), recommended_max_memory=lambda: 500)
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
        _guard.set_stage("segmentation")
        raise RuntimeError("test failure")

    monkeypatch.setattr(counter, "infer", fail)
    assert counter.main([str(audio), "--cache", str(cache), "--scratch", str(tmp_path),
                         "--output-dir", str(tmp_path / "results")]) == 1
    results = list((tmp_path / "results").glob("*/result.json"))
    result = json.loads(results[0].read_text())
    assert result["error"] == {"type": "RuntimeError", "message": "test failure"}
    assert result["input_unchanged"] and result["cache_unchanged"]
    assert result["temporary_directory_cleaned"]
    assert result["last_stage"] == "segmentation"
    assert result["stage_transitions"][-1]["stage"] == "segmentation"
    assert "observed_at_utc" in result["resources"][0]
    assert not list(tmp_path.glob("speaker-count-*"))


def test_progress_accepts_numpy_scalar_counts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    class ScalarCount:
        def __int__(self) -> int:
            return 100

    monkeypatch.setattr(counter.ResourceGuard, "check", lambda _self: None)
    monkeypatch.setattr(counter, "resource_sample", lambda: {
        "memory_pressure_level": 1, "active_competitor_pids": [],
    })
    counter.ResourceGuard().hook("segmentation", None, completed=ScalarCount(), total=ScalarCount())
    lines = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert lines[0]["stage_transition"] == "segmentation"
    assert lines[-1]["completed"] == lines[-1]["total"] == 100


@pytest.mark.parametrize("text,total,used,free", [
    ("total = 1024.00M used = 256.50M free = 767.50M (encrypted)",
     1024 * 1024**2, int(256.5 * 1024**2), int(767.5 * 1024**2)),
    ("total = 2.00G used = 1024.00K free = 1.00G", 2 * 1024**3, 1024**2, 1024**3),
    ("total = 0.00M used = 0.00M free = 0.00M", 0, 0, 0),
])
def test_swap_values_are_bytes(text: str, total: int, used: int, free: int) -> None:
    assert counter.swap_sample(text) == {
        "swap_total_bytes": total, "swap_used_bytes": used, "swap_free_bytes": free,
    }


@pytest.mark.parametrize("text", ["", "used = 1.00M", "total = ? used = ? free = ?"])
def test_unavailable_swap_is_not_fabricated(text: str) -> None:
    with pytest.raises(ValueError, match="Unrecognized"):
        counter.swap_sample(text)


def test_native_self_memory_layout_and_units(monkeypatch: pytest.MonkeyPatch) -> None:
    class Query:
        argtypes: list[Any] = []
        restype: Any = None

        def __call__(self, pid: int, flavor: int, pointer: Any) -> int:
            assert pid == os.getpid() and flavor == 0
            info = ctypes.cast(pointer, ctypes.POINTER(counter.ProcessMemoryInfo)).contents
            info.ri_resident_size = 4096
            info.ri_phys_footprint = 8192
            return 0

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(resource, "getrusage", lambda _who: SimpleNamespace(ru_maxrss=12288))
    monkeypatch.setattr(ctypes, "CDLL", lambda *_a, **_kw: SimpleNamespace(proc_pid_rusage=Query()))
    assert ctypes.sizeof(counter.ProcessMemoryInfo) == 96
    assert counter.ProcessMemoryInfo.ri_resident_size.offset == 64
    assert counter.ProcessMemoryInfo.ri_phys_footprint.offset == 72
    sample = counter.process_memory_sample()
    assert sample["process_rss_bytes"] == 4096
    assert sample["process_physical_footprint_bytes"] == 8192
    assert sample["process_rss_max_bytes"] == 12288
    assert sample["process_memory_source"] == "proc_pid_rusage_v0"


def test_footprint_unavailable_keeps_rss_without_guessing(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("unavailable")

    monkeypatch.setattr(ctypes, "CDLL", denied)
    monkeypatch.setattr(counter, "run_command", lambda _args: "1234\n")
    sample = counter.process_memory_sample()
    assert sample["process_rss_bytes"] == 1234 * 1024
    assert sample["process_physical_footprint_bytes"] is None
    assert sample["process_memory_source"] == "ps_rss_only"
    assert "process_memory_error" in sample
    monkeypatch.setattr(counter, "run_command", denied)
    missing = counter.process_memory_sample()
    assert missing["process_rss_bytes"] is None
    assert "process_rss_error" in missing


def test_swap_failure_does_not_replace_pressure_or_competitor_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def command(args: list[str]) -> str:
        if args[-1] == "kern.memorystatus_vm_pressure_level":
            return "2\n"
        if args[-1] == "vm.swapusage":
            raise OSError("swap unavailable")
        return f"{os.getpid()} 99 count_speakers.py\n9999999 15 ollama runner\n"

    monkeypatch.setattr(counter, "run_command", command)
    monkeypatch.setattr(counter, "process_memory_sample", lambda: {"process_rss_bytes": 123})
    sample = counter.resource_sample()
    assert sample["memory_pressure_level"] == 2
    assert sample["active_competitor_pids"] == [9999999]
    assert sample["process_rss_bytes"] == 123
    assert sample["swap_used_bytes"] is None and "swap_error" in sample
    with pytest.raises(RuntimeError, match="Competing inference"):
        counter.ResourceGuard().check(initial=True)


def test_stage_observation_cannot_reset_guard_or_flush_mps(monkeypatch: pytest.MonkeyPatch) -> None:
    now, pressure, actions = [0.0], [1], []
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    monkeypatch.setattr(counter, "resource_sample", lambda: {
        "memory_pressure_level": pressure[0], "active_competitor_pids": [],
        "process_rss_bytes": 123, "swap_used_bytes": 456,
    })
    mps = SimpleNamespace(driver_allocated_memory=lambda: 300, current_allocated_memory=lambda: 100,
                          recommended_max_memory=lambda: 500,
                          synchronize=lambda: actions.append("synchronize"),
                          empty_cache=lambda: actions.append("release"))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True)), mps=mps,
    ))
    guard = counter.ResourceGuard()
    guard.check(initial=True)
    now[0], pressure[0] = 10, 2
    guard.check()
    before = list(actions)
    now[0], pressure[0] = 11, 1
    guard.set_stage("segmentation")
    guard.set_stage("segmentation")  # no duplicate stage event
    assert actions == before and len(guard.stages) == 1
    assert guard.warning_since == guard.last_check == 10
    event = guard.stages[0]
    assert event["mps_observation_only"] is True and event["stage"] == "segmentation"
    assert event["mps_recommended_max_bytes"] == 500
    assert event["elapsed_seconds"] == 11 and event["stage_elapsed_seconds"] == 0
    assert event["pid"] == os.getpid() and event["observed_at_utc"].endswith("+00:00")
    now[0], pressure[0] = 40, 2
    with pytest.raises(RuntimeError, match="memory warning"):
        guard.check()
    assert guard.events[-1]["stage_elapsed_seconds"] == 29
    json.dumps({"guard": guard.events, "stages": guard.stages})


def test_initial_warning_still_rejects_before_hashing_or_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio, cache = tmp_path / "input.webm", tmp_path / "cache"
    audio.write_bytes(b"synthetic fixture")
    cache.mkdir()
    monkeypatch.setattr(counter, "resource_sample", lambda: {
        "memory_pressure_level": 2, "active_competitor_pids": [],
    })

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("must not hash audio/cache or load inference on initial warning")

    monkeypatch.setattr(counter, "infer", forbidden)
    monkeypatch.setattr(counter, "cache_fingerprints", forbidden)
    assert counter.main([str(audio), "--cache", str(cache), "--scratch", str(tmp_path),
                         "--output-dir", str(tmp_path / "results")]) == 1
    result = json.loads(next((tmp_path / "results").glob("*/result.json")).read_text())
    assert result["last_stage"] == "preflight" and result["stage_transitions"] == []
    assert "memory warning" in result["error"]["message"]
    assert "speaker_count" not in result and "input_sha256" not in result


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
