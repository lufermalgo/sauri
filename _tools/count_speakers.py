"""Offline, full-recording acoustic label counter. No Sauri imports or services."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MODEL_ID = "pyannote/speaker-diarization-3.1"
MODEL_CACHE_NAME = "models--pyannote--speaker-diarization-3.1"


def threshold_value(value: str) -> float:
    threshold = float(value)
    if not math.isfinite(threshold) or not 0 <= threshold <= 2:
        raise argparse.ArgumentTypeError("clustering threshold must be finite and in [0, 2]")
    return threshold


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("audio", type=Path, help="read-only original recording")
    cli.add_argument("--cache", type=Path, required=True, help="existing Torch pyannote cache (read-only)")
    cli.add_argument("--scratch", type=Path, required=True, help="temporary decode/cache parent")
    cli.add_argument("--output-dir", type=Path, required=True, help="private manifests, never audio or text")
    cli.add_argument("--clustering-threshold", type=threshold_value, default=None,
                     help="omit for unchanged cached pipeline baseline")
    return cli


def count_labels(annotation: Any) -> int:
    """Count all emitted labels; do not filter short turns or infer identities."""
    return len(annotation.labels())


def configured_parameters(defaults: dict[str, Any], threshold: float | None) -> dict[str, Any]:
    params = copy.deepcopy(defaults)
    if threshold is not None:
        params["clustering"]["threshold"] = threshold
    return params


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def cache_fingerprints(cache: Path) -> dict[str, str]:
    return {str(path.relative_to(cache)): digest(path)
            for path in sorted(cache.rglob("blobs/*")) if path.is_file()}


def deny_network(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("Network disabled: this experiment accepts only existing local models")


def enable_offline(work: Path, cache: Path) -> None:
    # Copy the small existing model cache: libraries cannot mutate the owner's cache.
    shutil.copytree(cache, work / "models", symlinks=False)
    for key, value in {
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
        "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "PYANNOTE_CACHE": str(work / "models"),
        "HF_HOME": str(work / "hf"), "XDG_CACHE_HOME": str(work / "cache"),
        "MPLCONFIGDIR": str(work / "mpl"), "TORCH_HOME": str(work / "torch"),
        "PYTORCH_ENABLE_MPS_FALLBACK": "0", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    }.items():
        os.environ[key] = value
    socket.socket.connect = deny_network  # type: ignore[method-assign]
    socket.socket.connect_ex = deny_network  # type: ignore[method-assign]
    socket.create_connection = deny_network


def run_command(args: list[str], timeout: int = 60) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout).stdout


def resource_sample() -> dict[str, Any]:
    pressure = int(run_command(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"]).strip())
    processes = run_command(["ps", "-axo", "pid=,%cpu=,command="])
    competitors = []
    for line in processes.splitlines():
        fields = line.strip().split(maxsplit=2)
        if len(fields) != 3 or int(fields[0]) == os.getpid():
            continue
        # CPU is an activity signal, not a GPU-utilization measurement. Idle loaded
        # servers are allowed; active inference is not. Never terminate others.
        command = fields[2].lower()
        engine = any(name in command for name in (
            "ollama runner", "ollama-runner", "llama-server", "mlx", "uvicorn native_main",
            "count_speakers.py", "acoustic_probe",
        ))
        if engine and float(fields[1]) >= 10:
            competitors.append(int(fields[0]))
    return {"memory_pressure_level": pressure, "active_competitor_pids": competitors}


class ResourceGuard:
    """Abort only our run on competing inference or sustained memory warnings."""

    def __init__(self) -> None:
        self.last_check = -math.inf
        self.warning_since: float | None = None
        self.events: list[dict[str, Any]] = []
        self.started = time.monotonic()

    def check(self, initial: bool = False) -> None:
        now = time.monotonic()
        if not initial and now - self.last_check < 10:
            return
        self.last_check = now
        mps_memory: dict[str, int] = {}
        torch = sys.modules.get("torch")
        if torch is not None and torch.backends.mps.is_available():
            # Release ONLY unused allocator blocks, never live tensors or weights.
            # This changes resource scheduling, not pipeline parameters or precision.
            mps_memory["mps_driver_bytes_before_release"] = torch.mps.driver_allocated_memory()
            torch.mps.synchronize()
            torch.mps.empty_cache()
            mps_memory["mps_driver_bytes"] = torch.mps.driver_allocated_memory()
            mps_memory["mps_live_tensor_bytes"] = torch.mps.current_allocated_memory()
        sample = {"elapsed_seconds": round(now - self.started, 3), **resource_sample(), **mps_memory}
        self.events.append(sample)
        if sample["active_competitor_pids"]:
            raise RuntimeError(f"Competing inference active: PIDs {sample['active_competitor_pids']}")
        if sample["memory_pressure_level"] > 1:
            if self.warning_since is None:
                self.warning_since = now
            if initial or now - self.warning_since >= 30:
                raise RuntimeError("macOS memory warning (initial or sustained for >=30 seconds)")
        else:
            self.warning_since = None

    def hook(self, step: str, _artifact: Any, **kwargs: Any) -> None:
        self.check()
        completed = int(kwargs["completed"]) if kwargs.get("completed") is not None else None
        total = int(kwargs["total"]) if kwargs.get("total") is not None else None
        if completed is None or completed == total or completed == 0 or completed % 100 == 0:
            print(json.dumps({"stage": step, "completed": completed, "total": total,
                              "elapsed_seconds": round(time.monotonic() - self.started, 2)}),
                  file=sys.stderr, flush=True)


def infer(args: argparse.Namespace, work: Path, result: dict[str, Any], guard: ResourceGuard) -> int:
    enable_offline(work, args.cache)
    import torch
    import yaml
    from pyannote.audio import Pipeline

    result["versions"] = {name: importlib.metadata.version(name) for name in (
        "pyannote.audio", "pyannote.core", "pyannote.pipeline", "torch", "torchaudio", "huggingface-hub",
    )}
    if not torch.backends.mps.is_available():
        raise RuntimeError("MPS unavailable; CPU fallback is not authorized")
    torch.set_num_threads(1)
    result["torch_cpu_threads"] = 1
    cached = work / "models" / MODEL_CACHE_NAME
    revision = (cached / "refs" / "main").read_text().strip()
    config_path = cached / "snapshots" / revision / "config.yaml"
    config = yaml.safe_load(config_path.read_text())
    result["model_revision"] = revision
    result["pipeline_config_sha256"] = digest(config_path)
    result["pipeline_constructor"] = config["pipeline"]
    result["parameters"] = configured_parameters(config["params"], args.clustering_threshold)
    # An existing local YAML plus copied dependency cache; no credentials required/read.
    pipeline = Pipeline.from_pretrained(config_path, use_auth_token=False)
    pipeline.instantiate(result["parameters"])
    pipeline.to(torch.device("mps"))
    if pipeline.device.type != "mps":
        raise RuntimeError("Pipeline did not select MPS")
    result["parameters_effective"] = pipeline.parameters(instantiated=True)
    result["device_effective"] = str(pipeline.device)
    result["batch_sizes"] = {"segmentation": pipeline.segmentation_batch_size,
                             "embedding": pipeline.embedding_batch_size}
    guard.check()
    wav_path = work / "decoded.wav"
    run_command(["ffmpeg", "-nostdin", "-v", "error", "-i", str(args.audio), "-vn", "-ar", "16000",
                 "-ac", "1", "-c:a", "pcm_s16le", str(wav_path)], timeout=600)
    with wave.open(str(wav_path), "rb") as decoded:
        result["duration_seconds"] = decoded.getnframes() / decoded.getframerate()
        result["decoded_format"] = {"sample_rate": decoded.getframerate(), "channels": decoded.getnchannels(),
                                    "sample_width_bytes": decoded.getsampwidth()}
    guard.check()
    started = time.monotonic()
    # Entire recording in ONE invocation, global clustering, no num/min/max_speakers.
    annotation = pipeline(str(wav_path), hook=guard.hook)
    result["inference_seconds"] = round(time.monotonic() - started, 3)
    return count_labels(annotation)


def interrupted(signum: int, _frame: Any) -> None:
    raise RuntimeError(f"Interrupted by signal {signum}")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    args.audio = args.audio.expanduser().resolve(strict=True)
    args.cache = args.cache.expanduser().resolve(strict=True)
    args.scratch = args.scratch.expanduser().resolve(strict=True)
    args.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_dir = args.output_dir / uuid.uuid4().hex
    run_dir.mkdir(mode=0o700)
    started = time.monotonic()
    result: dict[str, Any] = {
        "run_id": run_dir.name, "started_at": datetime.now(UTC).isoformat(), "status": "started",
        "model": MODEL_ID, "device_requested": "mps", "python": platform.python_version(),
        "input_name": args.audio.name, "input_bytes": args.audio.stat().st_size,
        "threshold_override": args.clustering_threshold, "speaker_count_constraints": None,
        "script_sha256": digest(Path(__file__)),
        "resource_policy": {"mps_release_unused_cache_at_checks": True, "mps_synchronize_before_release": True,
                            "sustained_memory_warning_seconds": 30},
    }
    (run_dir / "started.json").write_text(json.dumps(result, indent=2) + "\n")
    signal.signal(signal.SIGTERM, interrupted)
    guard = ResourceGuard()
    original_hash: str | None = None
    fingerprints: dict[str, str] | None = None
    try:
        guard.check(initial=True)
        original_hash = digest(args.audio)
        result["input_sha256"] = original_hash
        fingerprints = cache_fingerprints(args.cache)
        result["cached_model_blobs_sha256"] = fingerprints
        with tempfile.TemporaryDirectory(prefix="speaker-count-", dir=args.scratch) as directory:
            result["speaker_count"] = infer(args, Path(directory), result, guard)
        result["status"] = "succeeded"
    except (Exception, KeyboardInterrupt) as exc:
        result["status"] = "failed"
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        result["runtime_seconds"] = round(time.monotonic() - started, 3)
        result["resources"] = guard.events
        if original_hash is not None:
            result["input_unchanged"] = args.audio.is_file() and digest(args.audio) == original_hash
        if fingerprints is not None:
            result["cache_unchanged"] = cache_fingerprints(args.cache) == fingerprints
        if result.get("input_unchanged") is False or result.get("cache_unchanged") is False:
            result["status"] = "failed"
            result["error"] = {"type": "PreservationError", "message": "Input or cache changed"}
        result["temporary_directory_cleaned"] = not any(args.scratch.glob("speaker-count-*"))
        (run_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({**result, "manifest": str(run_dir / "result.json")}), flush=True)
    return 0 if result["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
