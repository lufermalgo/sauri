"""Bounded GPU output/memory verification, synthetic tensors only, no recordings."""
from __future__ import annotations

import argparse
import json
import os
import socket
import time
from pathlib import Path
from typing import Any

import count_speakers as counter
from mps_lstm_patch import load_patch, no_competing_pipeline, patch_segmentation


def verify(library: Path, result: dict[str, Any], iterations: int) -> None:
    result["preflight"] = counter.resource_sample()
    no_competing_pipeline()
    guard = counter.ResourceGuard()
    result["resources"] = guard.events
    guard.check(initial=True)
    os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "0"
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "1"
    socket.socket.connect = counter.deny_network  # type: ignore[method-assign]
    socket.socket.connect_ex = counter.deny_network  # type: ignore[method-assign]
    socket.create_connection = counter.deny_network
    import torch

    result["torch_imported"] = True
    result["patch"] = load_patch(library)
    torch.set_num_threads(1)
    torch.manual_seed(0)
    result["comparisons"] = []
    # Cover API modes cheaply before the representative repeated-input probe.
    cases = [(1, False, True, True, False), (2, True, False, True, True),
             (2, True, True, False, True)]
    with torch.inference_mode():
        for layers, bidirectional, batch_first, bias, with_state in cases:
            no_competing_pipeline()
            guard.check(initial=True)
            model = torch.nn.LSTM(3, 4, num_layers=layers, bidirectional=bidirectional,
                                  batch_first=batch_first, bias=bias).eval().to("mps")
            inputs = torch.randn((2, 7, 3) if batch_first else (7, 2, 3)).to("mps")
            shape = (layers * (2 if bidirectional else 1), 2, 4)
            state = (torch.randn(shape).to("mps"), torch.randn(shape).to("mps")) if with_state else None
            result["gpu_inference_started"] = True
            reference, ref_state = model(inputs, state)
            refs = [tensor.cpu() for tensor in (reference, *ref_state)]
            del reference, ref_state
            patch_segmentation(model)
            candidate, cand_state = model(inputs, state)
            actuals = [tensor.cpu() for tensor in (candidate, *cand_state)]
            errors = [float((actual - ref).abs().max()) for actual, ref in zip(actuals, refs, strict=True)]
            for actual, ref in zip(actuals, refs, strict=True):
                torch.testing.assert_close(actual, ref, rtol=0, atol=0)
            result["comparisons"].append({"layers": layers, "bidirectional": bidirectional,
                                          "batch_first": batch_first, "bias": bias,
                                          "provided_state": with_state, "max_abs_errors": errors})
            del model, inputs, state, candidate, cand_state, actuals, refs
            guard.check(initial=True)
        torch.manual_seed(0)
        model = torch.nn.LSTM(60, 128, num_layers=2, batch_first=True, bidirectional=True).eval().to("mps")
        inputs = torch.randn(4, 589, 60).to("mps")
        reference, ref_state = model(inputs)
        refs = [tensor.cpu() for tensor in (reference, *ref_state)]
        del reference, ref_state
        patch_segmentation(model)
        result["input_shape"] = [4, 589, 60]
        result["completed_iterations"] = 0
        result["samples"] = []
        for iteration in range(iterations):
            no_competing_pipeline()
            guard.check(initial=True)
            output, states = model(inputs)
            actuals = [tensor.cpu() for tensor in (output, *states)]
            for actual, ref in zip(actuals, refs, strict=True):
                torch.testing.assert_close(actual, ref, rtol=0, atol=0)
            del output, states, actuals
            guard.check(initial=True)
            sample = {"iteration": iteration + 1, **guard.events[-1]}
            result["samples"].append(sample)
            result["completed_iterations"] = iteration + 1
            if iteration in (0, 4, 9, 14, 19, iterations - 1):
                print(json.dumps(sample), flush=True)
        # Allow cold graph initialization, not per-call unbounded retention.
        warm = result["samples"][4]["mps_driver_bytes"]
        final = result["samples"][-1]["mps_driver_bytes"]
        result["driver_growth_after_iteration5_bytes"] = final - warm
        result["representative_outputs_bitwise_equal"] = True
        if final - warm > 64 * 1024 ** 2:
            raise RuntimeError("Candidate still grows >64 MiB after warmup; not validated")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=25)
    args = parser.parse_args()
    if not 25 <= args.iterations <= 100:
        parser.error("iterations must be between25 and100")
    result: dict[str, Any] = {"kind": "synthetic MPS operator verification, not acoustic validation",
                              "recordings_read": False, "torch_imported": False,
                              "gpu_inference_started": False, "status": "started", "pid": os.getpid()}
    started = time.monotonic()
    try:
        verify(args.library.expanduser().resolve(strict=True), result, args.iterations)
        result["status"] = "succeeded"
    except (Exception, KeyboardInterrupt) as exc:
        result["status"] = "failed"
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        result["runtime_seconds"] = round(time.monotonic() - started, 3)
        args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result), flush=True)
    return 0 if result["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
