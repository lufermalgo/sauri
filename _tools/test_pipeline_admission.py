"""Harness safety tests only; fixtures never establish acoustic quality/speed."""
from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

SPEC = importlib.util.spec_from_file_location("pipeline_admission", Path(__file__).with_name("pipeline_admission.py"))
assert SPEC and SPEC.loader
admission = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = admission
SPEC.loader.exec_module(admission)
CID = "a"*64
OWN = "b"*64
FOREIGN = "c"*64
DIGEST = "d"*64


def inventory() -> Any:
    return admission.Inventory(frozenset({CID}), frozenset({OWN}), "owned-run", frozenset())


def samples() -> list[Any]:
    return [admission.Snapshot(float(t), 1, 24*1024**3, 23*1024**3, 1024**3,
            (admission.Process(1, "Fri Nov 13 18:00:00 2026", DIGEST, "other", 0.0),),
            (admission.Container(CID, None), admission.Container(OWN, "owned-run")))
            for t in (0, 10, 20, 30)]


def test_exclusion_clear_is_never_an_automatic_gpu_authorization() -> None:
    result = admission.assess(samples(), inventory(), 30)
    assert result == {"state": "exclusions_clear_requires_manual_review", "automatic_launch": False,
                      "reasons": [], "blocked_pids": [], "blocked_container_ids": [],
                      "sample_count": 4, "swap_used_bytes": 23*1024**3}
    # High historical swap is reported, not silently interpreted as free capacity.
    assert result["swap_used_bytes"] == 23*1024**3


@pytest.mark.parametrize("kind", ["suite", "inference"])
def test_idle_cpu_does_not_exempt_suites_or_inference_jobs(kind: str) -> None:
    data = samples()
    process = admission.Process(337, "start", DIGEST, kind, 0.0)
    data[1] = replace(data[1], processes=(*data[1].processes, process))
    inv = replace(inventory(), idle_services=frozenset({(337, "start", DIGEST)}))
    result = admission.assess(data, inv, 30)
    assert result["state"] == "denied"
    assert result["blocked_pids"] == [337]
    assert "transient_suite_or_inference" in result["reasons"]


def test_busy_service_is_denied_even_with_explicit_idle_identity() -> None:
    data = samples()
    data[2] = replace(data[2], processes=(admission.Process(3, "start", DIGEST, "service", 10.0),))
    inv = replace(inventory(), idle_services=frozenset({(3, "start", DIGEST)}))
    assert admission.assess(data, inv, 30)["state"] == "denied"


@pytest.mark.parametrize("known", [False, True])
def test_service_requires_exact_reviewed_identity(known: bool) -> None:
    data = samples()
    data[2] = replace(data[2], processes=(admission.Process(3, "start", DIGEST, "service", 0.0),))
    inv = replace(inventory(), idle_services=frozenset({(3, "start", DIGEST)}) if known else frozenset())
    result = admission.assess(data, inv, 30)
    assert (result["state"] != "denied") == known


@pytest.mark.parametrize("field,value", [("started_at", "reused"), ("command_sha256", "e"*64)])
def test_pid_reuse_cannot_inherit_idle_confirmation(field: str, value: str) -> None:
    data = samples()
    process = admission.Process(3, "start", DIGEST, "service", 0.0)
    data[2] = replace(data[2], processes=(replace(process, **{field: value}),))
    inv = replace(inventory(), idle_services=frozenset({(3, "start", DIGEST)}))
    assert admission.assess(data, inv, 30)["blocked_pids"] == [3]


def test_unknown_running_container_blocks_even_without_test_cpu_activity() -> None:
    data = samples()
    data[0] = replace(data[0], containers=(*data[0].containers, admission.Container(FOREIGN, "qa771")))
    result = admission.assess(data, inventory(), 30)
    assert result["state"] == "denied"
    assert result["blocked_container_ids"] == [FOREIGN]


def test_owned_container_requires_id_and_run_label() -> None:
    data = samples()
    data[2] = replace(data[2], containers=(admission.Container(OWN, "foreign-run"),))
    assert admission.assess(data, inventory(), 30)["blocked_container_ids"] == [OWN]


def test_suite_in_earlier_sample_is_not_erased_by_last_clean_photo() -> None:
    data = samples()
    data[0] = replace(data[0], processes=(admission.Process(771, "start", DIGEST, "suite", 0.0),))
    assert admission.assess(data, inventory(), 30)["state"] == "denied"


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_requires_four_complete_observations(count: int) -> None:
    assert "insufficient_telemetry" in admission.assess(samples()[:count], inventory(), 30)["reasons"]


@pytest.mark.parametrize("times", [(0, 0, 0, 0), (0, 10, 30, 51), (0, 10, 9, 30)])
def test_requires_continuous_thirty_seconds(times: tuple[int, ...]) -> None:
    data = [replace(sample, measured_at=float(t)) for sample, t in zip(samples(), times, strict=True)]
    assert admission.assess(data, inventory(), 51)["state"] == "denied"


@pytest.mark.parametrize("field,value", [
    ("pressure", 2), ("pressure", 4), ("pressure", 0), ("pressure", True),
    ("measured_at", float("nan")), ("measured_at", 40),
    ("swap_used_bytes", -1), ("swap_free_bytes", 30*1024**3), ("swap_total_bytes", True),
    ("processes", ()),
])
def test_bad_telemetry_fails_closed(field: str, value: Any) -> None:
    data = samples()
    data[2] = replace(data[2], **{field: value})
    assert admission.assess(data, inventory(), 30)["state"] == "denied"


def test_stale_data_is_rejected() -> None:
    assert "stale_telemetry" in admission.assess(samples(), inventory(), 41)["reasons"]


def test_process_nonfinite_cpu_is_invalid_not_idle() -> None:
    data = samples()
    data[0] = replace(data[0], processes=(admission.Process(3, "start", DIGEST, "other", float("nan")),))
    assert "invalid_telemetry" in admission.assess(data, inventory(), 30)["reasons"]


@pytest.mark.parametrize("command,kind", [
    ("/project/.venv/bin/python -m pytest -q", "suite"),
    ("/bin/sh -c npm run test --workspace=portal", "suite"),
    ("vitest --run", "suite"), ("cargo test", "suite"), ("mypy .", "suite"),
    ("python native_memory_runner.py asr", "inference"),
    ("python count_speakers.py original", "inference"),
    ("python /scratch/real-pipeline/run.py", "inference"),
    ("python /scratch/service.py diar", "inference"),
    ("python -m uvicorn native_main:app", "service"),
    ("/Applications/Ollama.app/ollama runner --model model", "service"),
    ("python -m uvicorn native_main:app pytest", "suite"),
])
def test_process_classification_is_independent_of_cpu(command: str, kind: str) -> None:
    process, = admission.parse_processes("337 Fri Nov 13 18:00:00 2026 0.0 "+command)
    assert process.pid == 337 and process.kind == kind
    assert process.started_at == "Fri Nov 13 18:00:00 2026"
    assert command not in repr(process)


@pytest.mark.parametrize("text", ["", "123 bad", "3 Fri Nov 13 18:00:00 2026 nan pytest",
                                      "3 Fri Nov 13 18:00:00 2026 -1 pytest"])
def test_malformed_process_output_is_not_empty_success(text: str) -> None:
    with pytest.raises(admission.TelemetryError):
        admission.parse_processes(text)


def test_swap_parser_handles_real_macos_format() -> None:
    total, used, free = admission.parse_swap("total = 24576.00M  used = 24019.00M  free = 557.00M  (encrypted)")
    assert total == 24576*1024**2 and used == 24019*1024**2 and free == 557*1024**2


@pytest.mark.parametrize("text", ["missing", "total = nanM used = 1M free = 0M",
                                      "total = 1M used = 2M free = 0M", "total = 10M used = 1M free = 1M"])
def test_invalid_swap_is_not_a_capacity_signal(text: str) -> None:
    with pytest.raises(admission.TelemetryError):
        admission.parse_swap(text)


def test_check_observes_four_times_and_never_launches(monkeypatch: pytest.MonkeyPatch) -> None:
    launch = Mock(side_effect=AssertionError("No work may be launched"))
    monkeypatch.setattr(admission.subprocess, "Popen", launch)
    pause = Mock()
    data = iter(samples())
    result = admission.check(inventory(), observe=lambda: next(data), pause=pause, clock=lambda: 30.0)
    assert result["state"] == "exclusions_clear_requires_manual_review"
    assert pause.call_count == 3
    assert all(call.args == (10,) for call in pause.call_args_list)
    launch.assert_not_called()


def test_observation_error_aborts_without_retry_or_launch() -> None:
    observe = Mock(side_effect=admission.TelemetryError("failed"))
    pause = Mock()
    with pytest.raises(admission.TelemetryError):
        admission.check(inventory(), observe=observe, pause=pause)
    assert observe.call_count == 1
    pause.assert_not_called()


def inventory_json() -> dict[str, Any]:
    return {"schema_version": 1, "persistent_container_ids": [CID], "owned_container_ids": [OWN],
            "owned_run_id": "owned-run", "idle_services": []}


def test_inventory_needs_explicit_roles(tmp_path: Path) -> None:
    path = tmp_path/"inventory.json"
    path.write_text(json.dumps(inventory_json()))
    assert admission.Inventory.load(path) == inventory()


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", 2), ("persistent_container_ids", ["short"]),
    ("persistent_container_ids", [CID, CID]), ("persistent_container_ids", [OWN]),
    ("owned_run_id", None), ("owned_run_id", "../outside"), ("idle_services", None),
    ("idle_services", [{"pid": True, "started_at": "start", "command_sha256": DIGEST}]),
])
def test_bad_inventory_is_denied(tmp_path: Path, field: str, value: Any) -> None:
    data = inventory_json()
    data[field] = value
    path = tmp_path/"inventory.json"
    path.write_text(json.dumps(data))
    with pytest.raises(admission.TelemetryError):
        admission.Inventory.load(path)


def test_cli_failure_prints_categories_not_private_paths_or_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    sentinel = "PRIVATE_TRANSCRIPT_SENTINEL"
    monkeypatch.setattr(sys, "argv", ["pipeline_admission", "--inventory", str(tmp_path/sentinel)])
    assert admission.main() == 2
    text = capsys.readouterr().out
    assert sentinel not in text and "automatic_launch" in text
    assert json.loads(text)["state"] == "denied"


def test_collector_uses_only_readonly_commands_and_no_environment_values(monkeypatch: pytest.MonkeyPatch) -> None:
    invocations = []
    def read(args: list[str]) -> str:
        invocations.append(args)
        if args[:3] == ["sysctl", "-n", "kern.memorystatus_vm_pressure_level"]:
            return "1"
        if args[:3] == ["sysctl", "-n", "vm.swapusage"]:
            return "total = 2G used = 1G free = 1G"
        if args[0] == "ps":
            return "1 Fri Nov 13 18:00:00 2026 0.0 launchd"
        if args[:2] == ["docker", "ps"]:
            return OWN
        assert args[:4] == ["docker", "inspect", "--format", "{{json .Config.Labels}}"]
        return '{"sauri.performance.run":"owned-run"}'
    monkeypatch.setattr(admission, "command", read)
    observed = admission.collect()
    assert observed.pressure == 1 and observed.containers[0].identity == OWN
    assert len(invocations) == 5
    assert "Env" not in repr(invocations)


def test_observation_subprocess_errors_are_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admission.subprocess, "run", Mock(side_effect=OSError("PRIVATE_SENTINEL")))
    with pytest.raises(admission.TelemetryError, match="^observation_unavailable$"):
        admission.command(["ps"])
