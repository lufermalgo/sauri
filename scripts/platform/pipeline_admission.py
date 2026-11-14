"""Read-only, fail-closed preflight for isolated #907 runs; never launches work.

This is a harness check, not the production resource scheduler (spec T9).
Exclusion-clear snapshots require manual coordination; they are not GPU leases.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

IDENTITY = re.compile(r"[a-f0-9]{64}")
SUITE = re.compile(r"\b(?:pytest|vitest|mypy|ruff|tsc)\b|\bcargo\s+(?:test|build)\b|"
                   r"\b(?:npm|pnpm)\s+(?:run\s+)?(?:test|typecheck|build)\b")
INFERENCE = re.compile(r"count_speakers\.py|acoustic_probe|native_memory_runner\.py|"
                       r"real_pipeline\.py|service\.py\s+(?:asr|diar)|real-pipeline/run\.py")
SERVICE = re.compile(r"uvicorn\s+native_main|ollama\s+runner")
SWAP = re.compile(r"total\s*=\s*([\d.]+)([KMG]?)\s+used\s*=\s*([\d.]+)([KMG]?)"
                  r"\s+free\s*=\s*([\d.]+)([KMG]?)")


class TelemetryError(ValueError):
    """Missing/invalid observation; errors deliberately exclude command output."""


@dataclass(frozen=True)
class Process:
    pid: int
    started_at: str
    command_sha256: str
    kind: str
    cpu_percent: float


@dataclass(frozen=True)
class Container:
    identity: str
    run_id: str | None


@dataclass(frozen=True)
class Snapshot:
    measured_at: float
    pressure: int
    swap_total_bytes: int
    swap_used_bytes: int
    swap_free_bytes: int
    processes: tuple[Process, ...]
    containers: tuple[Container, ...]


@dataclass(frozen=True)
class Inventory:
    persistent_container_ids: frozenset[str]
    owned_container_ids: frozenset[str]
    owned_run_id: str | None
    idle_services: frozenset[tuple[int, str, str]]

    @classmethod
    def load(cls, path: Path) -> Inventory:
        value = json.loads(path.read_text())
        if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
            raise TelemetryError("invalid_inventory")
        sets: list[frozenset[str]] = []
        for key in ("persistent_container_ids", "owned_container_ids"):
            items = value.get(key)
            if not isinstance(items, list) or any(not isinstance(i, str) or not IDENTITY.fullmatch(i) for i in items):
                raise TelemetryError("invalid_container_inventory")
            if len(set(items)) != len(items):
                raise TelemetryError("duplicate_container_identity")
            sets.append(frozenset(items))
        if sets[0] & sets[1]:
            raise TelemetryError("ambiguous_resource_role")
        run = value.get("owned_run_id")
        if run is not None and (not isinstance(run, str) or not re.fullmatch(r"[a-z0-9-]{1,80}", run)):
            raise TelemetryError("invalid_run_identity")
        if sets[1] and run is None:
            raise TelemetryError("missing_run_identity")
        services = value.get("idle_services")
        if not isinstance(services, list):
            raise TelemetryError("missing_explicit_idle_service_inventory")
        identities = set()
        for item in services:
            if (not isinstance(item, dict) or type(item.get("pid")) is not int or item["pid"] <= 0
                    or not isinstance(item.get("started_at"), str) or not item["started_at"]
                    or not isinstance(item.get("command_sha256"), str)
                    or not IDENTITY.fullmatch(item["command_sha256"])):
                raise TelemetryError("invalid_process_identity")
            identities.add((item["pid"], item["started_at"], item["command_sha256"]))
        return cls(sets[0], sets[1], run, frozenset(identities))


def command(args: list[str]) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=True, timeout=10)
    except (subprocess.SubprocessError, OSError, UnicodeError) as error:
        raise TelemetryError("observation_unavailable") from error
    return result.stdout.strip()


def parse_swap(text: str) -> tuple[int, int, int]:
    match = SWAP.search(text)
    if match is None:
        raise TelemetryError("invalid_swap_observation")
    values = []
    for number, unit in zip(match.groups()[::2], match.groups()[1::2], strict=True):
        try:
            value = float(number) * 1024 ** {"": 0, "K": 1, "M": 2, "G": 3}[unit]
        except ValueError as error:
            raise TelemetryError("invalid_swap_observation") from error
        if not math.isfinite(value) or value < 0:
            raise TelemetryError("invalid_swap_observation")
        values.append(int(value))
    total, used, free = values
    if used > total or free > total or abs(total-used-free) > 1024*1024:
        raise TelemetryError("inconsistent_swap_observation")
    return total, used, free


def parse_processes(text: str) -> tuple[Process, ...]:
    result = []
    seen = set()
    for row in text.splitlines():
        # pid, five lstart columns, CPU, full command. Never export that command.
        columns = row.split(maxsplit=7)
        if len(columns) != 8:
            raise TelemetryError("invalid_process_observation")
        try:
            pid, cpu = int(columns[0]), float(columns[6])
        except ValueError as error:
            raise TelemetryError("invalid_process_observation") from error
        if pid <= 0 or pid in seen or not math.isfinite(cpu) or cpu < 0:
            raise TelemetryError("invalid_process_observation")
        seen.add(pid)
        text_command = columns[7]
        # A suite can never disguise itself as an idle persistent GPU server.
        kind = ("suite" if SUITE.search(text_command) else "inference" if INFERENCE.search(text_command)
                else "service" if SERVICE.search(text_command) else "other")
        result.append(Process(pid, " ".join(columns[1:6]),
                              hashlib.sha256(text_command.encode()).hexdigest(), kind, cpu))
    if not result:
        raise TelemetryError("missing_process_observation")
    return tuple(result)


def collect() -> Snapshot:
    started = time.monotonic()
    try:
        pressure = int(command(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"]))
    except ValueError as error:
        raise TelemetryError("invalid_pressure_observation") from error
    total, used, free = parse_swap(command(["sysctl", "-n", "vm.swapusage"]))
    processes = parse_processes(command(["ps", "-axo", "pid=,lstart=,%cpu=,command="]))
    identities = command(["docker", "ps", "--no-trunc", "-q"]).splitlines()
    containers = []
    for identity in identities:
        if not IDENTITY.fullmatch(identity):
            raise TelemetryError("invalid_container_observation")
        # Labels only: do not read environment values, credentials or Docker logs.
        try:
            labels = json.loads(command(["docker", "inspect", "--format", "{{json .Config.Labels}}", identity]))
        except json.JSONDecodeError as error:
            raise TelemetryError("invalid_container_observation") from error
        if labels is None:
            labels = {}
        if not isinstance(labels, dict):
            raise TelemetryError("invalid_container_observation")
        run = labels.get("sauri.performance.run")
        if run is not None and not isinstance(run, str):
            raise TelemetryError("invalid_container_observation")
        containers.append(Container(identity, run))
    return Snapshot(started, pressure, total, used, free, processes, tuple(containers))


def assess(samples: list[Snapshot], inventory: Inventory, now: float) -> dict[str, object]:
    """Four complete, exclusion-clear observations spanning >=30s; no CPU fallback."""
    reasons: set[str] = set()
    blocked_pids: set[int] = set()
    blocked_containers: set[str] = set()
    if not math.isfinite(now) or len(samples) < 4:
        reasons.add("insufficient_telemetry")
    previous = None
    for sample in samples:
        if (not math.isfinite(sample.measured_at) or sample.measured_at > now
                or type(sample.pressure) is not int or sample.pressure not in (1, 2, 4)
                or any(type(v) is not int or v < 0 for v in (
                    sample.swap_total_bytes, sample.swap_used_bytes, sample.swap_free_bytes))
                or sample.swap_used_bytes > sample.swap_total_bytes
                or sample.swap_free_bytes > sample.swap_total_bytes
                or abs(sample.swap_total_bytes-sample.swap_used_bytes-sample.swap_free_bytes) > 1024*1024
                or not sample.processes):
            reasons.add("invalid_telemetry")
        if previous is not None and not 10 <= sample.measured_at-previous <= 20:
            reasons.add("noncontinuous_telemetry")
        previous = sample.measured_at
        if sample.pressure != 1:
            reasons.add("memory_pressure")
        for process in sample.processes:
            if (type(process.pid) is not int or process.pid <= 0 or not process.started_at
                    or not IDENTITY.fullmatch(process.command_sha256)
                    or not math.isfinite(process.cpu_percent) or process.cpu_percent < 0
                    or process.kind not in ("suite", "inference", "service", "other")):
                reasons.add("invalid_telemetry")
            identity = (process.pid, process.started_at, process.command_sha256)
            if (process.kind in ("suite", "inference") or process.kind == "service"
                    and (process.cpu_percent >= 10 or identity not in inventory.idle_services)):
                blocked_pids.add(process.pid)
        for container in sample.containers:
            if container.identity in inventory.persistent_container_ids:
                continue
            if (container.identity in inventory.owned_container_ids and inventory.owned_run_id is not None
                    and container.run_id == inventory.owned_run_id):
                continue
            blocked_containers.add(container.identity)
    if samples and now-samples[-1].measured_at > 10:
        reasons.add("stale_telemetry")
    if blocked_pids:
        reasons.add("transient_suite_or_inference")
    if blocked_containers:
        reasons.add("unexcluded_running_containers")
    return {"state": "denied" if reasons else "exclusions_clear_requires_manual_review",
            "automatic_launch": False, "reasons": sorted(reasons),
            "blocked_pids": sorted(blocked_pids), "blocked_container_ids": sorted(blocked_containers),
            "sample_count": len(samples),
            "swap_used_bytes": samples[-1].swap_used_bytes if samples else None}


def check(
    inventory: Inventory, observe: Callable[[], Snapshot] = collect,
    pause: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    samples = []
    for index in range(4):
        if index:
            pause(10)
        samples.append(observe())
    return assess(samples, inventory, clock())


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--inventory", type=Path, required=True,
                     help="reviewed exact resource identities; never infer persistence from names")
    args = cli.parse_args()
    try:
        result = check(Inventory.load(args.inventory))
    except (TelemetryError, OSError, UnicodeError, json.JSONDecodeError):
        result = {"state": "denied", "automatic_launch": False, "reasons": ["telemetry_unavailable_or_invalid"]}
    print(json.dumps(result, allow_nan=False))
    return 0 if result["state"] == "exclusions_clear_requires_manual_review" else 2


if __name__ == "__main__":
    raise SystemExit(main())
