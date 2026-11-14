# #907 — Full original pipeline and MLX allocator correction

APX `task_e2a1fd161b4d4910`. Continuation authorized by Ansel on 2026-11-13: solve memory-only decoding and orchestration/native dependency separation, run the real full original, correct the measured dominant problem, and repeat without changing acoustic parameters. Ansel reviews/integrates; no deployment or main merge by this delivery.

## State (not a completed performance claim)

- #912 merged by Fer at `2026-11-13T23:05:13Z`, merge `6302c485adbcb540edc6eb1312346d8d30aece08`, head `a279aea04cd8aeda4d831df718cdc15c8a5e10f2`.
- Owner API/worker remain the existing `sauri-combined-api:6d03f2a`, running for three hours at inspection. Not rebuilt, restarted, replaced, or cleaned.
- This patch is based on main `6302c48`; it does not import the QA acoustic/alignment changes.
- Real experimental pipeline source is QA `bd638ee3a8fc6336a74235ab9f43c82b073ff6e7`. Its acoustic settings are held equal between attempts; this is NOT validation of installing all QA repairs or the main native endpoint.
- Full baseline did not finish. The bounded-allocator repeat completed REAL ASR/persistence, then stopped before MPS inference because the shared Torch2.5.1 LSTM retention evidence has no verified/approved dependency fix. No total speedup, WER/DER improvement, transcript equivalence, or complete quality acceptance is claimed. PR#917 remains DRAFT.

## Real path, isolation and transport

Original input: 400361891 bytes, SHA256 `9b53197391d1bbbb38962da948ddec8189f411bfffb6086100fc5f45a09c7857`, container duration 5654.853 s, decoded duration 5654.82 s. Original opened read-only; no clips or derived audio files.

Actual authenticated HTTP ingestion → disposable S3 bytes → signed RabbitMQ → production transcription worker → authenticated/capability-checked HTTP native adapter → real MLX; intended continuation is real MPS diarization → assignment/persistence → local Ollama → authenticated API readback. PG/MQ/S3 are real exclusive Docker resources. API/worker orchestration is hosted by the existing backend Python in this validation, not deployed in replacement Docker services. Explicit limitation: this is not a production-topology deployment acceptance test.

The validation adapter changes only preparation/transport: original webm bytes from the isolated object are hash-verified, piped to a child in the installed native Python, decoded as full 16kHz mono PCM16 into RAM, and passed as the model's supported waveform input. The native child has outbound sockets disabled and offline flags. No persistent audio derivatives; pyannote cache is copied into scratch; existing MLX snapshot is read locally. Missing asyncpg/aio_pika/httpx in native Python are avoided by using existing backend Python for orchestration. No installs or owner environment changes.

Fixed experimental config: whisper-large-v3-turbo, es, word_timestamps=true, condition_on_previous_text=false, hallucination_silence_threshold=2.0; VAD/granular/exclusive=false; pyannote3.1/MPS, basal clustering unchanged, segmentation/embedding batches4/4 (resource decomposition explicitly recorded, not a clustering change); qwen2.5:14b, fixed Spanish summary template. No imposed speaker count or CPU fallback. Holdout not used.

## Failed real baseline, preserved

Job `job_2107a8dae8cd4f58`, run `perf907-2ecb4725`, orchestration PID8611, native ASR8918. Source/harness hashes and numeric events are preserved under this session scratch `real-baseline/`.

- Authenticated upload200:3.585s; actual object read:3.428s; complete decode:9.391s.
- MLX continued computing for about16min. Two `sample` captures show actual Metal matmul/evaluation, not a network wait.
- `vmmap -summary 8918`:10.9GiB resident and10.6GiB swapped in its VM summary (not equated to physical footprint or all allocator cache).
- Host24GiB RAM; global swap24019MiB used/24576MiB total,557MiB free, memory pressure2. Global swap is not attributed entirely to this process.
- I cancelled only my ASR8918 and orchestration8611 before exhausting host resources. Pressure returned to1. No foreign process or model was killed/unloaded. Three exclusive containers were removed and absence checked; own resource sampler exited0.
- This is a failed/cancelled attempt, NOT a completed baseline with comparable quality or total latency.
- Earlier preflight-only failures (keyring format and broker startup race) were corrected; their exclusive containers were removed. They are not inference runs.

## Correction and terminal real repeat

Installed versions: mlx0.32.4, mlx-whisper0.4.3, pyannote.audio3.3.2, torch/torchaudio2.5.1, HFhub0.24.7. Installed MLX docs state default cache limit equals memory guideline, which defaults to1.5×recommended GPU working set. The repeat's API returned24481313587bytes (~22.8GiB) as both prior limits.

Set graph scheduling guideline to4GiB and free reusable cache limit to256MiB before publishing the native inference callable. These are allocator controls, not model/audio/decoder changes. The4GiB guideline is NOT a hard process memory cap; cache can transiently exceed256MiB until the next allocation. Startup fails closed if allocator configuration fails.

Repeat job `job_9b58b962562a40f2`, run `perf907-0cc6e543`, orchestration16196, native ASR16714; terminal, no process left running. Event/resource logs in session scratch `real-candidate/`; harness hashes/snapshot preserved before adding the subsequent MPS hold. Source backend remains bd638ee; ASR child retains the same acoustic parameters.

| Observed stage | Duration/result |
|---|---|
| Preparation/broker readiness before upload |66.000s (not inference) |
| Authenticated complete original upload |14.113s, HTTP200 |
| Actual S3 object read for ASR |3.654s,400361891bytes, hash verified |
| Full PCM decode in RAM |11.870s,5654.82s recording |
| Actual MLX transcribe call (includes its internal model load) |1366.802s;1506segments |
| Native ASR process |1380.662s, exit0 |
| Production transcription handler |1385.090s, committed1506turns |
| Admission before diarization |two15s waits while global pressure2; started next child only after pressure1 |
| MPS inference |NOT executed: child28100 exited78 with explicit dependency hold before importing Torch or decoding audio |
| Entire failed attempt through cleanup |1500.728s from preflight, NOT a complete-pipeline latency |

Separate model-load time and precise broker wait are unavailable, not zero. ASR emitted MLX peak4527877014bytes (~4.22GiB); active memory at progress1914006346bytes (~1.78GiB), largest sampled cache278970834bytes (~266MiB). Native max RSS3329409024bytes (~3.10GiB). `vmmap` observed physical footprint3.5GiB/peak4.9GiB early and2.9GiB/peak4.9GiB later. Do NOT add RSS/footprint/Metal as separate RAM/VRAM pools. Resource sampler recorded82samples, including global pressure1 AND2; bounded own allocator did not eliminate host-wide pressure. More memory counters do not retroactively prove the entire failed-baseline footprint was cache.

A read-only checkpoint of the disposable PG verified1506persisted turns,0invalid intervals against full duration, ordered sequence, start0/max end5650000ms. Canonical transcript SHA256`24209536a85122b3b9524a0dbb275fd97894891cec0d996e724f819355411f8b`; no transcript text in telemetry/evidence. These checks prove real persistence/temporal sanity, NOT WER/DER or factual accuracy. No speaker count, assignments, summary or complete API readback was obtained.

Both exclusive test stacks are now removed; `docker ps -a` confirms no perf907 containers. Native/orchestrator/checkpoint/sampler processes ended; expired private credentials removed. Original SHA256 after the run still matches the initial hash. No owner services/data/names/results were replaced or cleaned.

## Remaining GPU dependency boundary (not a CPU request)

While the healthy bounded ASR was running, I incorporated shared task_d1dd evidence: repeated whole-recording MPS segmentation failures and a separate LSTM reproducer with driver growth141672448→946962432bytes over25iterations while live tensors remained2924800bytes, after synchronize/empty_cache. That reproducer is synthetic diagnostic evidence, NOT full-pipeline/quality validation. Do not repeat the same known MPS failure merely with batches4 or switch to CPU.

Installed Torch2.5.1 has no verified in-environment fix. Upstream PR145503 identifies a missing autorelease in RnnOps.mm. I checked actual tagged SOURCE via GitHub API: v2.5.1 line331 ends `} mutableCopy];`; v2.7.1 line331 ends `} mutableCopy] autorelease];`. The PR API itself says merged=false, so its head commit is NOT evidence that a release contains it; the tagged-file check is the relevant evidence. This verifies source difference only, not wheel/runtime compatibility or all possible MPS leaks.

Recommended bounded continuation for Ansel to authorize/confirm under the dependency contract: evaluate a disposable native environment with matched Torch2.7.1/torchaudio2.7.1, existing pyannote3.3.2/checkpoints and unchanged model/config on GPU. Verify wheel availability, model-loading/security compatibility and operator outputs/retention before the original. Do not substitute the owner's environment, relax guards, install/download implicitly, or claim that an upgrade guarantees the pipeline. No CPU solution/fallback, model download or paid resource is proposed. I did not install a different Torch or retry MPS. Full GPU pipeline/quality remains pending that verified/allowed path.

Instrumentation note: after the deliberate hold, `diarization_committed` in the old harness meant only the fenced retry handler returned; it is NOT a successful artifact. The explicit hold/exit78 and missing final outputs take precedence, just as for the earlier transcription-handler name correction.

No completed transcript baseline exists for exact comparison. WER/DER require a human temporal reference not available here; the owner's count3 alone is not such a reference. Neither an in-progress run nor schema validation substitutes for quality acceptance.

## Local validation and closure

Actions were disabled with Fer's approval; do not request payment or claim CI passed. Relevant local controls from `.github/workflows/ci.yml`: backend pytest, Ruff, mypy and source compile/diff review; frontend/extension/Rust untouched, so their checks are not newly certified by this patch. Resource/auth/privacy contracts must remain intact. No test weakens those controls.

- RED before patch: `python -m pytest -p no:cacheprovider tests/asr_engine/test_native_memory_budget.py -q` →2 failures (unbounded callable published, allocator failure not preventing startup).
- GREEN: `python -m pytest -p no:cacheprovider tests/asr_engine tests/transcription -q` →74 passed in41.98s.
- `ruff check asr-engine/native_main.py tests/asr_engine/test_native_memory_budget.py` →PASS.
- `mypy --strict tests/asr_engine/test_native_memory_budget.py` →PASS. Native engine remains excluded from whole-project mypy by existing config; source compile checked separately before readiness.
- Whole-project static checks remain red: Ruff3 diagnostics in unchanged files; mypy82 diagnostics in8 unchanged files (191 source files checked), matching the recorded main debt. No diagnostics in either changed Python file; this is not a whole-project static PASS.
- Test doubles above exercise lifecycle/contracts only; they do not certify real inference or acoustic quality.

Pending before ready: completed pipeline (or precise remaining failure), real repeat/quality evidence, final SHA-bound local validation, diff review, and publication. Do not close the APX objective or call this a total-performance delivery while these are pending. Cleanup at every terminal attempt removes only this harness's containers and private temporary credentials; original and owner's resources stay intact.
