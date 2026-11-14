# Isolated MPS LSTM autorelease candidate (#910 / PR #914)

## Status and boundary

**Operator verification passed on real MPS; full-recording count is still incomplete.** Outputs/hidden/cell states were bitwise equal to the original operator in three API cases and25 representative calls; driver allocation stayed201408512 bytes (zero repeated-call growth). This is not acoustic accuracy or pipeline performance. The corrected full-recording4/4 run subsequently stopped on the unchanged global-memory guard after65.574s, without a count. Keep this delivery draft/unmerged pending its complete acceptance criteria.

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
- After those workloads ended, operator verification succeeded in7.056s with pressure1 throughout: three API modes and all25 representative output/state comparisons bitwise equal; driver201408512B and live tensors2924800B constant. This corrects the demonstrated native retention, without claiming all model/system memory problems solved.
- A subsequent corrected full-original4/4 run reached2800/5646 segmentation windows and stopped at65.574s under the unchanged memory guard: warning samples35.297–65.487s (30.190s). MPS driver **after** synchronization/release remained273006592B throughout those samples instead of rising per call. **Before** synchronization/release it was1355137024B. Their difference is not a measured CUDA-like reserved-memory category or proof of allocator-only causality. Physical footprint ended2227357352B, RSS637370368B. Do not sum RSS and Metal. No embeddings, clustering, count or tuning was completed. Original/cache hashes and temporary cleanup passed.
- Next bounded investigation targets transient allocation/cache peaks and batch4-versus1 equivalence in the same cached segmentation/embedding models, not another identical retry. That probe was rejected before model loading by a new performance GPU workload; no GPU was interrupted. Real input distribution/count remain pending. Private manifests/logs are attached to task_d1ddf9cdac7d4cf2, not committed.
- Targeted Python unit/regression, Ruff and strict mypy are separate from these unperformed GPU checks. See the private delivery evidence for exact commands/results and the single regression skip; no global-backend or end-to-end pass is claimed.
