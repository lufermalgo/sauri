from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import build_mps_lstm_patch as builder
import count_speakers as counter
import count_speakers_mps_patch as launcher
import mps_lstm_patch as patch

SOURCE = '''namespace at::native {
std::tuple<Tensor, Tensor> _lstm_mps(const Tensor& input,
string key = "lstm_";
NSMutableDictionary* results = [@{
} mutableCopy];
return input;
}
std::tuple<Tensor, std::vector<Tensor>, std::vector<Tensor>> lstm_mps_backward
UNUSED_BACKWARD_BODY
'''


def test_patch_only_changes_release_name_cache_and_registration() -> None:
    output = builder.patched_forward(SOURCE)
    assert "UNUSED_BACKWARD_BODY" not in output
    assert "sauri_lstm_mps_fixed" in output
    assert 'key = "sauri_autorelease_251_"' in output
    assert "} mutableCopy] autorelease];" in output
    assert "return input;" in output
    assert "TORCH_LIBRARY_IMPL(sauri_mps_251, MPS" in output
    assert "TORCH_LIBRARY_IMPL(sauri_mps_251, CPU" not in output


@pytest.mark.parametrize("source", ["", SOURCE + SOURCE, SOURCE.replace("} mutableCopy];", "changed")])
def test_source_mismatch_fails_closed(source: str) -> None:
    with pytest.raises(ValueError):
        builder.patched_forward(source)


def test_competing_pipeline_includes_idle_orchestrator_not_shell(monkeypatch: Any) -> None:
    rows = f"{os.getpid()} /bin/python /tmp/verify_mps_lstm_patch.py\n"
    rows += "123 /bin/zsh echo /tmp/real_pipeline.py\n"
    rows += "456 /bin/python /tmp/unrelated.py\n"
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: rows)
    patch.no_competing_pipeline()
    # Darwin truncates comm to16 columns when another column follows it.
    rows += "789 /opt/homebrew/Ce /opt/homebrew/bin/python /tmp/real_pipeline.py\n"
    with pytest.raises(RuntimeError, match="789"):
        patch.no_competing_pipeline()


@pytest.mark.parametrize("version,available", [("2.6.0", True), ("2.5.1", False)])
def test_no_wrong_abi_or_cpu_fallback(monkeypatch: Any, version: str, available: bool) -> None:
    fake = SimpleNamespace(__version__=version,
                           version=SimpleNamespace(git_version=builder.TORCH_GIT_VERSION),
                           backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: available)))
    monkeypatch.setitem(sys.modules, "torch", fake)
    with pytest.raises(RuntimeError):
        patch.load_patch(Path("/not/read"))


def test_patch_refuses_autograd(monkeypatch: Any) -> None:
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(is_grad_enabled=lambda: True))
    with pytest.raises(RuntimeError, match="eval-only"):
        patch.fixed_lstm_forward(SimpleNamespace(), object())


def test_patch_refuses_tampered_binary(monkeypatch: Any, tmp_path: Path) -> None:
    fake = SimpleNamespace(__version__="2.5.1",
                           version=SimpleNamespace(git_version=builder.TORCH_GIT_VERSION),
                           backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True)))
    monkeypatch.setitem(sys.modules, "torch", fake)
    library = tmp_path / "patch.dylib"
    library.write_bytes(b"not-the-compiled-binary")
    (tmp_path / "build.json").write_text(json.dumps({"binary_sha256": "mismatch"}))
    with pytest.raises(RuntimeError, match="provenance mismatch"):
        patch.load_patch(library)


def test_distribution_retains_short_and_unassigned_labels() -> None:
    annotation = SimpleNamespace(
        labels=lambda: ["long", "short", "unused"],
        itertracks=lambda **kwargs: iter([
            (SimpleNamespace(start=0.0, end=10.0), "track", "long"),
            (SimpleNamespace(start=9.0, end=9.1), "overlap", "short"),
            (SimpleNamespace(start=11.0, end=12.0), "track", "long"),
        ]),
    )
    assert launcher.label_distribution(annotation) == [
        {"label": "long", "turns": 2, "summed_turn_seconds": 11.0},
        {"label": "short", "turns": 1, "summed_turn_seconds": 0.1},
        {"label": "unused", "turns": 0, "summed_turn_seconds": 0.0},
    ]


@pytest.mark.parametrize("raises", [False, True])
def test_launcher_restores_counter_without_editing_it(monkeypatch: Any, raises: bool) -> None:
    originals = (counter.parser, counter.infer, counter.apply_batch_sizes,
                 counter.count_labels, counter.ResourceGuard.check)

    def fake_main(argv: Any) -> int:
        assert counter.parser is not originals[0]
        cli = counter.parser()
        args = cli.parse_args(["/input", "--cache", "/cache", "--scratch", "/work",
                               "--output-dir", "/output", "--mps-patch-library", "/patch"])
        assert args.clustering_threshold is None
        assert not hasattr(args, "num_speakers")
        if raises:
            raise RuntimeError("synthetic unit-test exception")
        return 0

    monkeypatch.setattr(counter, "main", fake_main)
    if raises:
        with pytest.raises(RuntimeError, match="synthetic"):
            launcher.main([])
    else:
        assert launcher.main([]) == 0
    assert originals == (counter.parser, counter.infer, counter.apply_batch_sizes,
                          counter.count_labels, counter.ResourceGuard.check)
