# Isolated MPS LSTM autorelease candidate (#910 / PR #914)

## Status and boundary

**Candidate only: GPU output/memory verification and full-recording count are NOT complete.** A successful build or MPS dispatch registration does not certify the operator, acoustic accuracy or performance. Keep this delivery unmerged until the checks below are actually observed.

This continues the approved standalone count experiment in `local-speaker-count-experiment.md`, not a production architecture change. GPU remains mandatory; historical CPU proposals are superseded. No model/dependency installation, full Torch rebuild, device fallback, speaker constraints, new model or holdout execution is involved. Native inference remains on MPS; ordinary CPU bookkeeping/clustering is unchanged.

The base counter and its concurrent telemetry changes are preserved. The added launcher changes only its current Python process and restores hooks at exit. No production imports, services, DB, names or existing results are modified.

## Minimal native correction, not an upgrade claim

The existing Torch 2.5.1 synthetic probe grew about768 MiB over25 calls while live tensors remained constant, despite per-call synchronization/cache release. Upstream [#145503](https://github.com/pytorch/pytorch/pull/145503/files) adds autorelease to the per-call `results` dictionary in `RnnOps.mm`. This is a retained-object fix, not an instruction to add an outer Python autorelease pool.

Version inspection found the original `mutableCopy` without this release in [v2.6.0](https://github.com/pytorch/pytorch/blob/v2.6.0/aten/src/ATen/native/mps/operations/RnnOps.mm), and the release in [v2.7.0](https://github.com/pytorch/pytorch/blob/v2.7.0/aten/src/ATen/native/mps/operations/RnnOps.mm). An unspecified upgrade is therefore not a verified remedy. Changing Torch would also require matching torchaudio and accounting for changed deserialization defaults.

Instead, `build_mps_lstm_patch.py` compiles **only the v2.5.1 forward operator** using the existing Xcode compiler/SDK, Torch headers and libraries. It fetches public upstream source/license, not a dependency wheel, model or recording. Exact reviewed source SHA256 and installed Torch git commit are checked. Build/source/binary hashes and command are recorded in private scratch. No ninja, package installation, native environment replacement or owner engine restart is needed.

The generated operator retains the original calculations. Changes: add the upstream dictionary autorelease, use a distinct function/cache name, omit backward code and register an isolated MPS-only namespace. It never overrides the installed ATen operator. `mps_lstm_patch.py` wraps only the loaded segmentation model's `nn.LSTM`, retaining its parameters, states, precision and native calculations. It rejects training/autograd, projections, unbatched/packed inputs, wrong Torch ABI, non-MPS/float32 inputs and mismatched build provenance. Unsupported cases fail; they do not fall back.

## Reproduce safely

Use the existing native Python and private scratch. The build writes only into the specified scratch directory:

```bash
"$HOME/.local/share/sauri/native-engines/venv/bin/python" -B \
  _tools/build_mps_lstm_patch.py /absolute/private/scratch/native-patch

"$HOME/.local/share/sauri/native-engines/venv/bin/python" -B \
  _tools/verify_mps_lstm_patch.py \
  --library /absolute/private/scratch/native-patch/lstm_autorelease.dylib \
  --output /absolute/private/scratch/operator-verification.json
```

The verifier refuses an existing performance/ASR/counter executor even if its instantaneous CPU activity is low. It also uses the existing memory policy, with an immediate warning stop for this bounded synthetic probe. It compares GPU outputs/hidden/cell states bit-for-bit for several API modes, then compares25 representative calls at `[4,589,60]` with the unpatched MPS operator. After warmup, growth above64 MiB fails the candidate; that test threshold is not a change to the real-run memory guard. Synthetic tests cannot prove acoustic correctness or complete-pipeline throughput.

**Only after operator verification succeeds**, and without another GPU workload, run the original complete recording through the existing counter:

```bash
"$HOME/.local/share/sauri/native-engines/venv/bin/python" -B \
  _tools/count_speakers_mps_patch.py /absolute/path/to/authorized-original.webm \
  --cache "$HOME/.cache/torch/pyannote" \
  --scratch /absolute/private/scratch/work \
  --output-dir /absolute/private/scratch/results \
  --segmentation-batch-size 4 --embedding-batch-size 4 \
  --mps-patch-library /absolute/private/scratch/native-patch/lstm_autorelease.dylib
```

Baseline has no threshold override, no expected-count input, and one full-recording pipeline call/global clustering. Keep the existing sustained-warning guard, offline model loading and cleanup. New manifests identify the patch and aggregate raw-label turn counts/summed turn seconds, without persisting voice, text or annotation timelines. Summed turns are not exclusive speech and raw labels are not historical UI identities. Do not report a count, distribution, tuning comparison, accuracy, or total runtime before a complete real result exists. Holdout B stays reserved.

## Evidence observed in this delivery

- Native translation unit compiled successfully with the existing Torch2.5.1 ABI. A separate process loaded the library and confirmed an MPS kernel registered; no recording/model inference was performed by that load.
- Initial verification failed before GPU execution on a real macOS warning. After fixing a Darwin truncated-`comm` detection gap, the verifier independently rejected the active performance orchestrator/ASR runner. No competitor was signalled or restarted.
- Thus real GPU output equality/memory stabilization are still unverified; no original recording or tuning was started by this candidate. Private manifests/logs are attached to task_d1ddf9cdac7d4cf2, not committed.
- Targeted Python unit/regression, Ruff and strict mypy are separate from these unperformed GPU checks. See the private delivery evidence for exact commands/results and the single regression skip; no global-backend or end-to-end pass is claimed.
