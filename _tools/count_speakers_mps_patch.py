"""Run the existing full-recording counter with a process-local MPS release fix.

No changes to count_speakers.py, production, model weights, clustering or guards.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import count_speakers as counter
from mps_lstm_patch import load_patch, no_competing_pipeline, patch_segmentation


def label_distribution(annotation: Any) -> list[dict[str, Any]]:
    """Aggregate emitted acoustic intervals only; never store audio or timelines."""
    labels = annotation.labels()
    totals: dict[Any, dict[str, Any]] = {
        label: {"label": str(label), "turns": 0, "summed_turn_seconds": 0.0} for label in labels
    }
    for segment, _track, label in annotation.itertracks(yield_label=True):
        totals[label]["turns"] += 1
        totals[label]["summed_turn_seconds"] += float(segment.end - segment.start)
    for total in totals.values():
        total["summed_turn_seconds"] = round(total["summed_turn_seconds"], 6)
    return list(totals.values())


def main(argv: list[str] | None = None) -> int:
    original_parser = counter.parser
    original_infer = counter.infer
    original_batch = counter.apply_batch_sizes
    original_count = counter.count_labels
    original_check = counter.ResourceGuard.check
    active_result: dict[str, Any] = {}
    state: dict[str, Any] = {}

    def parser() -> argparse.ArgumentParser:
        cli = original_parser()
        cli.description = __doc__
        cli.add_argument("--mps-patch-library", type=Path, required=True,
                         help="isolated local build; no dependency is replaced")
        return cli

    def apply_batch_sizes(pipeline: Any, segmentation: int | None, embedding: int | None) -> None:
        original_batch(pipeline, segmentation, embedding)
        state.update(load_patch(active_result["library"]))
        state["modules"] = patch_segmentation(pipeline._segmentation.model)

    def count_labels(annotation: Any) -> int:
        active_result["result"]["label_distribution"] = label_distribution(annotation)
        active_result["result"]["distribution_semantics"] = (
            "Acoustic turns and summed turn seconds, not exclusive speech or ASR assignments; "
            "raw labels do not identify historical UI speakers. No timeline persisted."
        )
        return original_count(annotation)

    def infer(args: argparse.Namespace, work: Path, result: dict[str, Any], guard: Any) -> int:
        library = args.mps_patch_library.expanduser().resolve(strict=True)
        active_result.update(library=library, result=result)
        result["gpu_memory_patch"] = state
        result["patch_launcher_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        result["patch_module_sha256"] = hashlib.sha256(
            (Path(__file__).parent / "mps_lstm_patch.py").read_bytes()).hexdigest()
        return original_infer(args, work, result, guard)

    def check(guard: counter.ResourceGuard, initial: bool = False) -> None:
        import time

        if initial or time.monotonic() - guard.last_check >= 10:
            no_competing_pipeline()
        original_check(guard, initial=initial)

    counter.parser = parser
    counter.apply_batch_sizes = apply_batch_sizes
    counter.count_labels = count_labels
    counter.infer = infer
    try:
        with patch.object(counter.ResourceGuard, "check", check):
            return counter.main(argv)
    finally:
        counter.parser = original_parser
        counter.apply_batch_sizes = original_batch
        counter.count_labels = original_count
        counter.infer = original_infer


if __name__ == "__main__":
    sys.exit(main())
