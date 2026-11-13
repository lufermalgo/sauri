# Standalone local speaker-count experiment

## Authority, boundary and traceability

- Issue #910; APX `task_d1ddf9cdac7d4cf2`; owner authorization 2026-11-13.
- This is an isolated experiment contract, not a new product feature, approved Spectra phase, or production correction. `speaker-oversegmentation-jose-maria` was a session name, not a spec found in the repository. The existing `fix-transcript-word-fragments` spec describes related attribution/admission defects, but does not authorize changing production here.
- Implementer: Nahuel. Delivery: PR ready for Ansel's review, **no merge**.
- Calibration recording A has owner-reported truth 3. Recording B (truth 6) is reserved: do not run it or use it to select parameters during this task. Private filenames, manifests and content remain outside Git.
- Count acoustic labels only: `len(annotation.labels())`. No transcription, turn filtering, identity recognition, speaker constraints, or segment output. A correct count on A does not certify identities or out-of-sample accuracy.

## CLI contract

Use the already-installed native Python 3.11 environment (pyannote.audio 3.3.2, torch/torchaudio 2.5.1). No installation, model download or paid API is part of this task.

```bash
PYTHONDONTWRITEBYTECODE=1 "$HOME/.local/share/sauri/native-engines/venv/bin/python" \
  _tools/count_speakers.py /absolute/path/to/authorized-recording.webm \
  --cache "$HOME/.cache/torch/pyannote" \
  --scratch /absolute/private/scratch/work \
  --output-dir /absolute/private/scratch/results
```

The scratch directory must already exist. Baseline omits `--clustering-threshold`. An optional finite `[0, 2]` override changes only `clustering.threshold`; there is deliberately no device option or `num/min/max_speakers` argument. Do not supply the expected count to the pipeline.

The CLI:

1. Checks macOS memory pressure and active competing local inference processes (including Ollama/llama/MLX/native servers). Never terminates another process. This process-name/CPU signal is not an exhaustive scheduler or a GPU utilization measurement; operator preflight is still required. An idle loaded model is not treated as active inference.
2. Hashes the read-only original and model blobs. Copies the existing small model cache into a temporary private directory, disables network connections and Hugging Face downloads/implicit credentials, and redirects library caches to scratch. It does not read Sauri credentials or connect to DB, object storage or services.
3. Loads the cached 3.1 YAML and dependency weights, records the revision, effective parameters, batch sizes and library versions. Requires MPS and disables PyTorch's unsupported-operation CPU fallback. Pyannote's ordinary CPU clustering remains unchanged; “MPS” describes neural inference, not every operation.
4. Decodes the full original with ffmpeg to temporary mono 16 kHz PCM16 WAV. Calls the pipeline **once for the entire recording**; the pipeline performs internal windows and global clustering. Defaults to cached official batch sizes (32/32), with optional explicit technical batch overrides recorded separately as described below; keeps centroid method, min cluster size 12, overlap exclusion and segmentation min_duration_off 0. Only the threshold can vary. PyTorch CPU intra-op threads are 1, recorded as a technical execution setting.
5. Counts every emitted label without inspecting text, dropping short voices or forcing a target. Deletes temporary WAV/models/library caches on normal exit, exception, SIGINT or SIGTERM. SIGKILL/power loss cannot guarantee cleanup; inspect the private scratch path before reuse.
6. Writes distinct UUID run directories with `started.json` and `result.json`. Final stdout is JSON containing count (only on success), parameters/model/version, decoded duration, timings, error (if any), resource samples and preservation checks. Progress on stderr contains stage/counters only; no audio, transcript, annotation intervals or embedding arrays are exported. All failed attempts are preserved. Exit 0 means successful completion, not acoustic accuracy.

The guard synchronizes the MPS command queue and releases only **unused** allocator cache at resource checks (technical memory scheduling, not a quality-parameter change). It records driver/live-tensor bytes before/after release. It checks during pipeline callbacks, every 10 seconds at most: initial memory warning rejects the run; a warning during inference must persist at least 30 seconds before aborting this run. There is no CPU-idle cutoff, arbitrary inference deadline or CPU fallback. Callbacks cannot interrupt a single long native operation; this is not a hard real-time memory isolation mechanism. A busy CPU can make the run slower without being a failure. Do not weaken memory controls to obtain a count.

## Bounded calibration method

- Run the unchanged cached baseline first (`threshold=0.7045654963945799`). Report its real count before selecting any candidate.
- If it over-counts, evaluate increasing threshold values sequentially (at most three variants), because larger centroid-distance cut thresholds generally merge more clusters. If it under-counts, evaluate decreasing values. The exact values and justification must be recorded after observing the baseline, not chosen by reading B.
- Hold all other quality parameters, full audio, device and the explicitly recorded execution batching constant across any baseline/tuning comparison. No open grid, short-cluster deletion, manual label merging or expected-count input.
- Retain the baseline, every failed attempt and every variant. Stop if resources or controls prevent a complete baseline; an incomplete run is not a count and is not grounds for threshold selection.
- B remains untouched until Ansel reviews this stage. Later validation needs the frozen candidate, not further tuning on B.

## Verification inventory

`_tools/test_count_speakers.py` checks label count/empty output, baseline and single-field overrides, invalid thresholds, no speaker/device constraint arguments, progress scalar normalization, resource guard behavior, error manifests/cleanup, offline-network denial and production isolation. Synthetic fixtures test the CLI contract only, **not diarization quality**.

Project Python validation: backend `pytest`, `ruff check .`, `mypy .`, plus targeted checks for the standalone tool (outside backend's normal discovery):

```bash
backend/.venv/bin/python -m pytest -p no:cacheprovider -q _tools/test_count_speakers.py
backend/.venv/bin/ruff check --config backend/pyproject.toml _tools/count_speakers.py _tools/test_count_speakers.py
backend/.venv/bin/mypy --strict --ignore-missing-imports _tools/count_speakers.py _tools/test_count_speakers.py
```

The native runtime requires existing pyannote/torch libraries; `--ignore-missing-imports` in the contract typecheck is not a runtime dependency check. Actual model loading and inference must be recorded separately in the private execution evidence. No Rust or TypeScript files are changed.

## Authorized technical continuation, 2026-11-13

Ansel explicitly authorized reducing inference batches to resolve the existing execution, without changing the model, full-recording invocation, clustering baseline or resource guard. Optional `--segmentation-batch-size` and `--embedding-batch-size` now change only inference batching; absent flags preserve cached 32/32. Manifests retain cached, requested and effective sizes. A 4/4 continuation was started sequentially after confirming no active counter/inference competitor and macOS memory pressure level 1. This is not threshold tuning, not the unchanged-32/32 execution baseline, and not an accuracy-equivalence claim. Earlier attempts and manifests remain untouched. CPU fallback remains prohibited; holdout remains excluded. Targeted validation of this delta: 27 tests passed, Ruff passed, strict mypy passed. The 4/4 run failed safely after 66.750 seconds during segmentation (last printed progress 1200/5646), before embeddings or clustering. Four consecutive level-2 pressure samples spanned 30.129 seconds (elapsed 36.435–66.564); MPS driver allocation after cache release grew from 1.25 to 4.29 GiB, while live-tensor allocation stayed at 32,480,512 bytes. No inference competitor was detected. Error: `RuntimeError: macOS memory warning (initial or sustained for >=30 seconds)`. Original/cache hashes and scratch cleanup passed. No speaker count or threshold variant exists. No identical retry or new model inference was launched after this failure.

Source inspection of installed pyannote.audio 3.3.2 confirms `segmentation_batch_size` updates `_segmentation.batch_size` (speaker_diarization.py:181–186), not just a manifest field. `Inference.infer` uses `torch.inference_mode()` and returns CPU NumPy outputs (core/inference.py:197–230); `slide` appends those outputs and reports progress between batches (lines 297–346). Therefore the failure occurs in neural segmentation, not the global clustering matrix. Driver allocation growth with approximately constant live tensors remains unexplained; these counters do not prove a driver leak or distinguish allocator/backend causes. Smaller batches 4/4 did not resolve the observed memory condition, and the record of an earlier 32→4→1 ladder is not reproduced as new evidence here. A further identical or smaller-batch trial is not justified by this evidence alone. The concrete blocker is sustained macOS memory pressure during MPS segmentation despite synchronization and unused-cache release. A stable-memory execution environment or a separately reviewed backend/device execution change is needed; no silent CPU fallback, dependency change, process termination, or relaxed guard is authorized.

## Delivery verification, 2026-11-13

- Tool contract tests: **19 passed**. Targeted Ruff and strict mypy: **PASS**. Real installed `pyannote.core.Annotation` synthetic contract: four turns, three labels, **PASS** (not acoustic accuracy).
- Existing diarization-engine regression tests: **23 passed**.
- Backend full non-marked-integration discovery (`pytest --continue-on-collection-errors -m 'not integration'`): **528 passed, 2 failed, 5 skipped, 2 deselected, 10 errors**. Some live tests lack the integration marker: nine PostgreSQL tests reject missing isolated QA configuration before connecting; the object-store test fails on missing `OBJECT_STORE_ENDPOINT` before creating a client. Remaining collection error: missing `app.transcription.processing_pipeline`; remaining failure: absent speaker-review route in generated schema. No services were started to mask these failures.
- Backend-wide Ruff: **3 existing errors** in untouched imports/datetime usage; backend-wide mypy: **82 errors in 8 untouched files**. `git diff origin/main -- backend` is empty. These broad checks are not represented as green.
- Real MPS runs loaded the cached weights offline and processed the complete recording's segmentation windows, but **no final label count was produced**. First attempt exposed a NumPy scalar progress-serialization bug (fixed and regression-tested). Subsequent attempts hit the memory guard; releasing unused MPS cache, then synchronizing before release, did not resolve it. Last run observed memory-warning level 2 in four consecutive samples over 31.26 seconds, driver memory approximately 6.04 GiB after release, and exited safely after 70.259 seconds. No OOM or model defect is claimed.
- All run manifests and errors remain private outside Git, with original/cache preservation true and temporary cleanup true. **No threshold variants were selected or run; B was not opened or processed.** The experiment objective (real baseline followed by tuning) remains blocked, even though the CLI implementation is available for review.
- Initial recommendation was a sustained memory-available window for the unchanged MPS baseline. **Superseded by the bounded native-path diagnosis below:** normal initial pressure is insufficient evidence that this runtime will complete. Do not repeat the exhausted batch-size ladder, silently switch to CPU, force a count, kill/unload someone else's processes, or weaken the memory guard.

## Read-only telemetry continuation, 2026-11-13

Ansel subsequently authorized completing observability and one MPS 4/4 baseline **only after** transient Docker suites have finished and an operator preflight observes normal pressure throughout a stable window. This does not fix or dismiss the native LSTM diagnostic below, authorize CPU/dependency changes, or permit an identical retry after another failure without new cause. Calibration/holdout boundaries remain unchanged.

The CLI now records current RSS and physical footprint from Darwin `proc_pid_rusage` flavor 0 for **its own PID only** (SDK `sys/resource.h` `rusage_info_v0`, 96 bytes). `resource.getrusage` supplies high-water RSS with Darwin byte units. If the optional native query is unavailable, RSS falls back to `ps` KiB converted to bytes; footprint stays null and an error/source is recorded, never inferred from RSS. Swap total/used/free come from `sysctl vm.swapusage`, converted to byte units; unavailable optional fields are null with errors. Required pressure/competitor queries remain fail-closed.

Existing `resources` guard samples additionally carry PID, UTC observation time, current stage, total/stage elapsed time, collection duration and MPS recommended working-set bytes. Existing driver-before-release, driver-after-release and live-tensor counters retain their meanings. Driver minus live is **not** a reserved/free-memory counter; RSS/footprint/Metal are not disjoint amounts to add on unified memory.

Separate `stage_transitions` snapshots observe input/cache hashing, cache copy/imports, model loading/loaded, audio decode/decoded, pipeline audio loading, callback stages and pipeline completion. They only read counters: no extra synchronization, cache release, warning timer changes or rate-limit reset. First segmentation callback follows full-waveform loading, making the CPU-materialization boundary visible without altering pyannote. Pyannote does not emit a clustering-start hook in this version, so an error after embeddings but before reconstruction cannot be attributed to a more precise substage from these hooks alone. `last_stage` and transitions are preserved on failure; progress remains JSON Lines without audio/text/embedding payloads. The original guard conditions, ten-second cadence, thirty-second sampled-warning policy, synchronization/release actions and full-recording invocation are unchanged.

Validation: **38 contract tests passed**, targeted Ruff and strict mypy passed, and **23 backend diarization regression tests passed**. A real Python 3.11 self-telemetry smoke read successfully returned native RSS/footprint and system swap without importing Torch or opening audio. The native environment has no pytest module; the contract suite runs with the existing project test environment (Python 3.13), not a newly installed dependency. These checks do not validate acoustic precision or prove the new counters under full model load. Earlier backend-wide failures above remain unresolved; they were not rerun as extra competing suites for this telemetry-only delta.

The read-only operator preflight at 23:40:57–23:41:30 UTC sampled seven times over 30 seconds: all pressure levels were 1 and no inference competitor matched the detector, but three `perf907-*` transient services remained active throughout. Therefore **no new recording inference was launched**. The acoustic task owns no Docker resources to remove; no QA, owner data or active suites from another session were stopped. Preflight and private names/measurements are preserved in task evidence, not Git. A stable-pressure window alone does not satisfy the separate no-transient-suite condition.

## Bounded native-path diagnosis, 2026-11-13

No full-recording inference was repeated for this diagnosis. A standalone synthetic probe used the installed Torch 2.5.1, a fresh evaluation-mode bidirectional 2-layer `nn.LSTM(60,128)`, input `[4,589,60]`, seed 0, MPS and `torch.inference_mode()`. Those dimensions match PyanNet's source defaults, **not independently verified cached-checkpoint hyperparameters**. The probe copied outputs to CPU, deleted them, synchronized MPS and released unused cache on **every** iteration. The existing guard rejected any memory warning immediately at each iteration, stricter than the real-run policy. Network access was denied. No recording, checkpoint or model cache was read.

It completed 25 iterations in **5.813 s**, with pressure level 1 and no competitor detected. After synchronize/release, driver allocations rose from **141,672,448** to **946,962,432 bytes** (about **768 MiB** growth over 24 more calls), while live tensors remained **2,924,800 bytes**. The process then exited; no inference was left running. Thus the installed fused MPS LSTM path reproduces growing allocations independently of pyannote audio/embeddings/clustering. This is memory evidence only, not an acoustic validation or proof that it explains every allocation in the complete model.

Version-matched upstream evidence: [PyTorch #145374](https://github.com/pytorch/pytorch/issues/145374) reports this pattern on Torch 2.5.1. Its [v2.5.1 RnnOps.mm](https://github.com/pytorch/pytorch/blob/v2.5.1/aten/src/ATen/native/mps/operations/RnnOps.mm) contains a per-call results dictionary created by `mutableCopy` without `autorelease`; [PR #145503](https://github.com/pytorch/pytorch/pull/145503) adds that autorelease and describes the retained MPSGraphTensorData/MPSNDArrays. Later [PR #194459](https://github.com/pytorch/pytorch/pull/194459) discusses another retention mechanism, but its proposed synchronization remedy was **not** assumed effective here: the local per-iteration-sync probe still grew. A dependency upgrade is not certified as a complete solution by those references.

**Next technical decision:** explicitly review a CPU execution contract for this isolated experiment, using the same cached model/full recording/float precision/quality baseline and macOS memory guard, with no automatic fallback or production changes. It may be slower and does not imply acoustic equivalence. Alternatively, review an isolated dependency upgrade and validate MPS memory first; that is not authorized by this experiment's unchanged-runtime contract. No native binary, recurrent implementation, dependency environment, device, resource guard or production code was changed. The diagnostic script/log/report are private task attachments. There is still no real count, quality tuning, or holdout result.
