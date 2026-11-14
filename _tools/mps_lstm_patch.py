"""Process-local, eval-only MPS LSTM release patch for the isolated #910 experiment."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import types
from pathlib import Path
from typing import Any

from build_mps_lstm_patch import SOURCE_SHA256, TORCH_GIT_VERSION, UPSTREAM_FIX


def no_competing_pipeline() -> None:
    """Do not race the separate ASR/performance executor even when CPU% is low."""
    output = subprocess.check_output(["ps", "-axo", "pid=,comm=,args="], text=True)
    competitors = []
    pattern = re.compile(
        r"/(native_memory_runner|real_pipeline|count_speakers|count_speakers_mps_patch|"
        r"verify_mps_lstm_patch)\.py(?:\s|$)"
    )
    for line in output.splitlines():
        fields = line.strip().split(maxsplit=2)
        if (len(fields) == 3 and int(fields[0]) != os.getpid()
                and "python" in Path(fields[2].split(maxsplit=1)[0]).name.lower()
                and pattern.search(fields[2])):
            competitors.append(int(fields[0]))
    if competitors:
        raise RuntimeError(f"Competing GPU pipeline still active: PIDs {competitors}; not signalled")


def load_patch(library: Path) -> dict[str, Any]:
    import torch

    if torch.__version__ != "2.5.1" or torch.version.git_version != TORCH_GIT_VERSION:
        raise RuntimeError("Patch requires verified Torch 2.5.1 ABI/commit")
    if not torch.backends.mps.is_available():
        raise RuntimeError("MPS is required; no CPU fallback")
    manifest = json.loads((library.parent / "build.json").read_text())
    binary_hash = hashlib.sha256(library.read_bytes()).hexdigest()
    if (manifest.get("binary_sha256") != binary_hash
            or manifest.get("source_sha256") != SOURCE_SHA256
            or manifest.get("fix_commit") != UPSTREAM_FIX
            or manifest.get("torch_git_version") != TORCH_GIT_VERSION):
        raise RuntimeError("Patch binary/build provenance mismatch")
    torch.ops.load_library(str(library))
    return {"fix_commit": UPSTREAM_FIX, "source_sha256": SOURCE_SHA256,
            "binary_sha256": binary_hash, "torch_git_version": TORCH_GIT_VERSION,
            "device": "mps", "scope": "process-local segmentation LSTM; no dependency replaced"}


def fixed_lstm_forward(module: Any, inputs: Any, hx: Any = None) -> Any:
    import torch

    if (torch.is_grad_enabled() or module.training or module.proj_size != 0
            or not isinstance(inputs, torch.Tensor)
            or inputs.ndim != 3 or inputs.device.type != "mps" or inputs.dtype != torch.float32):
        raise RuntimeError("Patch supports eval-only unprojected float32 batched MPS LSTM")
    module._update_flat_weights()
    batch = inputs.shape[0 if module.batch_first else 1]
    directions = 2 if module.bidirectional else 1
    if hx is None:
        zeros = inputs.new_zeros(module.num_layers * directions, batch, module.hidden_size)
        hx = (zeros, zeros)
    module.check_forward_args(inputs, hx, None)
    outputs = torch.ops.sauri_mps_251.lstm(
        inputs, list(hx), module._flat_weights, module.bias, module.num_layers,
        module.dropout, False, module.bidirectional, module.batch_first,
    )
    return outputs[0], (outputs[1], outputs[2])


def patch_segmentation(model: Any) -> list[str]:
    import torch

    patched = []
    for name, module in model.named_modules():
        if isinstance(module, torch.nn.LSTM):
            if module.proj_size != 0:
                raise RuntimeError("Projected LSTM is outside this patch")
            module.forward = types.MethodType(fixed_lstm_forward, module)
            patched.append(name)
    if not patched:
        raise RuntimeError("No segmentation LSTM found; refuse an unpatched claimed candidate")
    return patched
