"""Build only the 2.5.1 MPS LSTM forward with upstream #145503's release fix.

Isolated experiment for #910. Never installs/replaces Torch or another dependency.
The generated translation unit retains PyTorch's license and source provenance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path

SOURCE_URL = (
    "https://raw.githubusercontent.com/pytorch/pytorch/v2.5.1/"
    "aten/src/ATen/native/mps/operations/RnnOps.mm"
)
LICENSE_URL = "https://raw.githubusercontent.com/pytorch/pytorch/v2.5.1/LICENSE"
UPSTREAM_FIX = "833f58cd4b8bb625a109d9abf209555a5470c1e7"
SOURCE_SHA256 = "265f2a7bf9e253ab6419bcad8bda5731c4e1683304d4dfdb496765fe9fd90eaa"
TORCH_GIT_VERSION = "a8d6afb511a69687bbb2b7e88a3cf67917e1697e"
REGISTRATION = r'''
} // namespace at::native

TORCH_LIBRARY(sauri_mps_251, module) {
  module.def("lstm(Tensor input, Tensor[] hx, Tensor[] params, bool has_biases, "
             "int num_layers, float dropout_p, bool train, bool bidirectional, "
             "bool batch_first) -> (Tensor, Tensor, Tensor, Tensor, Tensor, Tensor)");
}
TORCH_LIBRARY_IMPL(sauri_mps_251, MPS, module) {
  module.impl("lstm", TORCH_FN(at::native::sauri_lstm_mps_fixed));
}
'''


def patched_forward(source: str) -> str:
    """Fail closed if source layout differs; no mathematical change to forward."""
    marker = "std::tuple<Tensor, std::vector<Tensor>, std::vector<Tensor>> lstm_mps_backward"
    if source.count(marker) != 1:
        raise ValueError("Unexpected upstream backward boundary")
    forward = source.split(marker)[0]
    replacements = (
        ("Tensor> _lstm_mps(const Tensor& input,", "Tensor> sauri_lstm_mps_fixed(const Tensor& input,"),
        ('string key = "lstm_"', 'string key = "sauri_autorelease_251_"'),
        ("* results = [@{", "* results = [[@{"),
        ("} mutableCopy];", "} mutableCopy] autorelease];"),
    )
    for old, new in replacements:
        if forward.count(old) != 1:
            raise ValueError(f"Unexpected upstream occurrence count for {old!r}")
        forward = forward.replace(old, new)
    return "#include <torch/library.h>\n" + forward + REGISTRATION


def build(directory: Path) -> dict[str, object]:
    import torch

    if torch.__version__ != "2.5.1" or torch.version.git_version != TORCH_GIT_VERSION:
        raise RuntimeError("This patch requires the verified upstream Torch 2.5.1 ABI/commit")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    torch_root = Path(torch.__file__).resolve().parent
    # Only public upstream source/license are retrieved, never wheels/models/audio.
    with urllib.request.urlopen(SOURCE_URL, timeout=30) as response:
        source_bytes = response.read()
    if hashlib.sha256(source_bytes).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("Upstream source hash differs from reviewed v2.5.1 RnnOps.mm")
    source = source_bytes.decode("utf-8")
    patched = patched_forward(source)
    with urllib.request.urlopen(LICENSE_URL, timeout=30) as response:
        license_bytes = response.read()
    (directory / "LICENSE.pytorch").write_bytes(license_bytes)
    (directory / "RnnOps.v2.5.1.mm").write_bytes(source_bytes)
    path = directory / "lstm_autorelease.mm"
    path.write_text(patched)
    sdk = subprocess.check_output(["xcrun", "--show-sdk-path"], text=True).strip()
    compiler = subprocess.check_output(["xcrun", "--find", "clang++"], text=True).strip()
    output = directory / "lstm_autorelease.dylib"
    command = [compiler, "-std=c++17", "-O2", "-fPIC", "-fno-objc-arc", "-shared",
               "-undefined", "dynamic_lookup", "-isysroot", sdk,
               "-I", str(torch_root / "include"),
               "-I", str(torch_root / "include/torch/csrc/api/include"),
               "-L", str(torch_root / "lib"), "-Wl,-rpath," + str(torch_root / "lib"),
               "-ltorch_cpu", "-ltorch", "-lc10", "-framework", "Foundation",
               "-framework", "Metal", "-framework", "MetalPerformanceShaders",
               "-framework", "MetalPerformanceShadersGraph", str(path), "-o", str(output)]
    manifest = {"source_url": SOURCE_URL, "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
                "fix_commit": UPSTREAM_FIX, "generated_sha256": hashlib.sha256(patched.encode()).hexdigest(),
                "torch_version": torch.__version__, "torch_git_version": torch.version.git_version,
                "torch_root": str(torch_root), "compiler_command": command,
                "dependency_installations": False, "recordings_read": False}
    (directory / "build.json").write_text(json.dumps(manifest, indent=2) + "\n")
    subprocess.run(command, check=True, timeout=180)
    manifest["binary_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    (directory / "build.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.directory.resolve()), indent=2))
