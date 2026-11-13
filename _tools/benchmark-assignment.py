#!/usr/bin/env python3
"""#907 / T3: CPU-only attribution benchmark, never acoustic inference.

Run with PYTHONPATH=backend and the project's backend virtualenv Python.
Default: explicitly synthetic, deterministic anonymous intervals. For a replay:
  --input /path/intervals.json --input-kind real-replay
JSON accepts ONLY {"speakers": [1, 2], "turns": [[start_ms, end_ms], ...],
"segments": [[speaker_index, start_ms, end_ms], ...]}. Speaker values are tie-break
sequences; IDs/labels are generated locally. No text/audio/names are accepted.
A real-replay label is a caller provenance declaration, not proof of acoustics;
never reconstruct original detections from final assignments. Fixtures use
--input-kind fixture. The original baseline is loaded from git, not copied from
an optimized helper. All index construction is included in candidate timings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import statistics
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, cast

from app.diarization.assignment import assign_turns
from app.diarization.diarization_engine import SpeakerSegment
from app.diarization.labeling import Speaker

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "backend/app/diarization/assignment.py"
AssignmentFunction = Callable[..., list[tuple[str, Speaker, int]]]


@dataclass
class Turn:
    id: str
    start_ms: int
    end_ms: int


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def load_input(path: Path) -> tuple[list[Turn], list[SpeakerSegment], list[Speaker]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"turns", "segments", "speakers"}:
        raise ValueError("Input must contain only turns, segments and speakers")
    for field in ("turns", "segments", "speakers"):
        if not isinstance(data[field], list):
            raise ValueError("Input fields must be lists")
    if any(type(sequence) is not int for sequence in data["speakers"]):
        raise ValueError("Speaker sequences must be integers")
    for field, width in (("turns", 2), ("segments", 3)):
        if any(not isinstance(row, list) or len(row) != width or any(type(x) is not int for x in row)
               for row in data[field]):
            raise ValueError("Intervals must be integer arrays of the documented width")
    speakers = [Speaker(str(i), f"anonymous-{i}", seq) for i, seq in enumerate(data["speakers"])]
    if any(not 0 <= row[0] < len(speakers) for row in data["segments"]):
        raise ValueError("Segment speaker index is out of range")
    return (
        [Turn(str(i), start, end) for i, (start, end) in enumerate(data["turns"])],
        [SpeakerSegment(str(label), start, end) for label, start, end in data["segments"]],
        speakers,
    )


def synthetic(turn_count: int, segment_count: int, speaker_count: int, seed: int) -> tuple[
    list[Turn], list[SpeakerSegment], list[Speaker],
]:
    rng = random.Random(seed)
    speakers = [Speaker(str(i), f"anonymous-{i}", i + 1) for i in range(speaker_count)]
    turns = [Turn(str(i), i * 800, i * 800 + (0 if i % 61 == 0 else 2600 if i % 11 == 0 else 650))
             for i in range(turn_count)]
    segments = [SpeakerSegment(str(i % speaker_count), i * 600, i * 600 + rng.choice([300, 700, 1300]))
                for i in range(segment_count)]
    # Overlap, duplicated detections and arbitrary order are intentional.
    segments.extend(segments[::13])
    rng.shuffle(segments)
    rng.shuffle(turns)
    rng.shuffle(speakers)
    return turns, segments, speakers


def benchmark(
    baseline: AssignmentFunction, turns: list[Turn], segments: list[SpeakerSegment], speakers: list[Speaker],
    *, exclusive: bool, repetitions: int, warmup: int,
) -> dict[str, Any]:
    expected = baseline(turns, segments, speakers, require_exclusive=exclusive)
    assert assign_turns(turns, segments, speakers, require_exclusive=exclusive) == expected
    for _ in range(warmup):
        baseline(turns, segments, speakers, require_exclusive=exclusive)
        assign_turns(turns, segments, speakers, require_exclusive=exclusive)
    samples: dict[str, list[float]] = {"baseline": [], "indexed": []}
    for iteration in range(repetitions):
        variants = [("baseline", baseline), ("indexed", assign_turns)]
        if iteration % 2:
            variants.reverse()
        for name, function in variants:
            started = perf_counter()
            result = function(turns, segments, speakers, require_exclusive=exclusive)
            samples[name].append(perf_counter() - started)
            assert result == expected, "Output changed during measurement"
    baseline_median = statistics.median(samples["baseline"])
    indexed_median = statistics.median(samples["indexed"])
    return {
        "mode": "exclusive" if exclusive else "accumulated", "equivalent": True,
        "assignment_count": len(expected), "samples_seconds": samples,
        "baseline_median_seconds": baseline_median, "indexed_median_seconds": indexed_median,
        "speedup": baseline_median / indexed_median,
        "median_reduction_percent": 100 * (1 - indexed_median / baseline_median),
        "meets_20_percent_stage_target": indexed_median <= 0.8 * baseline_median,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline-ref", default="178f893551405774bc5d9006d0eb90cd4c33f586")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--input-kind", choices=["real-replay", "fixture"])
    parser.add_argument("--turns", type=int, default=1500)
    parser.add_argument("--segments", type=int, default=2000)
    parser.add_argument("--speakers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=907)
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--warmup", type=int, default=1)
    args = parser.parse_args()
    if args.repetitions < 7 or args.warmup < 1:
        parser.error("Require at least 7 repetitions and 1 warmup")
    if bool(args.input) != bool(args.input_kind):
        parser.error("--input and --input-kind must be specified together")
    if min(args.turns, args.segments, args.speakers) < 1:
        parser.error("Synthetic sizes must be positive")
    turns, segments, speakers = (load_input(args.input) if args.input else
                                synthetic(args.turns, args.segments, args.speakers, args.seed))
    source = git("show", f"{args.baseline_ref}:{SOURCE}")
    namespace: dict[str, Any] = {"__name__": "assignment_baseline"}
    exec(compile(source, "assignment_baseline", "exec"), namespace)
    baseline = cast(AssignmentFunction, namespace["assign_turns"])
    fingerprint = json.dumps({
        "turns": [(t.start_ms, t.end_ms) for t in turns],
        "segments": [(s.raw_label, s.start_ms, s.end_ms) for s in segments],
        "speakers": [(s.raw_label, s.sequence) for s in speakers],
    }, sort_keys=True).encode()
    report = {
        "stage": "assign_turns including index construction", "input_kind": args.input_kind or "synthetic",
        "scope": "CPU interval attribution only; not acoustic quality or whole-pipeline speed",
        "baseline_revision": git("rev-parse", args.baseline_ref), "candidate_revision": git("rev-parse", "HEAD"),
        "candidate_source_sha256": hashlib.sha256((ROOT / SOURCE).read_bytes()).hexdigest(),
        "candidate_dirty": bool(git("status", "--porcelain", "--", SOURCE)),
        "input_sha256": hashlib.sha256(fingerprint).hexdigest(),
        "python": platform.python_version(), "platform": platform.platform(),
        "counts": {"turns": len(turns), "segments": len(segments), "speakers": len(speakers)},
        "seed": args.seed if not args.input else None, "repetitions": args.repetitions, "warmup": args.warmup,
        "results": [benchmark(baseline, turns, segments, speakers, exclusive=exclusive,
                              repetitions=args.repetitions, warmup=args.warmup) for exclusive in (False, True)],
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
