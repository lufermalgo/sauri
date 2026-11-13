# T25 / #293 — real integration regression and RED-gate discrepancy

## Status

Implemented additional **regression coverage**, not an observed RED delivery. T25 remains pending its approved RED criterion; T26 is not declared complete. No production behavior or acceptance criterion was silently changed. Fer retains merge authority. This evidence proposes accepting regression proof for this already-wired path; it does not itself approve that amendment.

Pre-test candidate: `dcbf452`, combining T14 PR #874 and T16 PR #873, including T10/T12 predecessors. Existing T9 and T14 tests are preserved. No implementation file was changed by this task.

## Observed behavior

New test `test_real_provider_lifecycle_default_duplicate_failure_and_transcript_deletion` in `backend/tests/integration/test_summary_pipeline.py` uses:

- Actual FastAPI ASGI routes with authenticated synthetic owner.
- PostgreSQL 16 in an exclusively disposable Docker container.
- Actual signed RabbitMQ publications, dispatcher and production summary consumer.
- Actual configured local Ollama HTTP adapter and already-installed `qwen2.5:14b`; no provider replacement, model download, personal transcript or personal service startup.
- An observing RabbitMQ subclass delegates unchanged to actual subscriptions/handlers and only records completed source deliveries. The duplicate assertion waits for real handler completion, not an arbitrary sleep or an empty queue that could still contain unacknowledged work.

The test verifies explicit template selection, personal default selection, successive distinct generations, snapshot/version preservation after editing the template, successful persisted reads, real signed duplicate delivery without another artifact, and failure of a deliberately nonexistent local model through bounded broker retries to terminal `failed`. A later failure preserves the earlier successful summary. Deleting the transcript removes its summaries and the read route returns 404. Existing pipeline coverage checks transcript commit alone never requests a summary; T12 regression coverage checks successful retry with a frozen snapshot.

This is technical verification using synthetic data, not product acceptance, accuracy certification, a permanent deployment, or proof of the full `app.worker` process startup. The HTTP client in this run executes on the host; the separate prior T14/T16 runtime evidence covers Docker-to-Ollama connectivity.

## Commands and observed results

Run from `backend/`, using the existing project virtual environment at the root checkout (without editing the root). The new test opts in using `SAURI_QA_OLLAMA_URL` and `SAURI_QA_OLLAMA_MODEL`.

- `pytest tests/integration/test_summary_pipeline.py -q`: **16 passed**, no skips, 19.70s. Includes the controlled disposable-broker restart case.
- `pytest tests/templates tests/summaries -q`: **39 passed**, no skips, 7.93s. Includes PostgreSQL 16 migration upgrade/downgrade and real broker terminal delivery. Three pre-existing Alembic `path_separator` deprecation warnings.
- `ruff check tests/integration/test_summary_pipeline.py`: PASS.
- `ruff format --check tests/integration/test_summary_pipeline.py`: PASS.
- `mypy app tests/integration/test_summary_pipeline.py`: PASS, 74 source files. Running from repository root initially missed backend configuration and reported unrelated stub errors; the specified backend working directory passes without suppressions.
- `git diff --check`: PASS.

Disposable databases were explicitly segregated by each suite's safety contract: `sauri_t9_t25` (pipeline), `sauri_t11_t25` (worker) and `sauri_t15_t25` (read API), plus the migration suite's temporary database. Safety guards were not weakened. PostgreSQL and RabbitMQ were created from already-installed images with `--pull never`, bound only to localhost. A trap removed both containers and anonymous volumes on every attempt; final absence was checked. No custom network or persistent owner volume was created.

Initial infrastructure attempts are NOT RED proof: one ran before RabbitMQ's AMQP listener was ready; another correctly refused the T9 database namespace for the T11 suite. Readiness was corrected to a real AMQP handshake and each suite received its dedicated database. The final complete run above passed.

## RED criterion discrepancy and proposed amendment (awaiting Fer)

The approved T25 criterion expects tests to fail because final integration wiring is missing before T26. On the required accumulated predecessor candidate, this path is already wired and the newly added actual-provider test passes on its first functional run. Removing working wiring, disabling a route, or inventing an assertion solely to obtain RED would falsify the evidence and is not authorized.

**Proposal:** accept T25 as integration regression evidence for behavior already implemented by T10/T12/T14/T16; retain mandatory RED-before-GREEN for any genuinely missing behavior discovered later. Treat T26 as a verification-only unit if its approved invariants continue to pass without additional wiring. No product scope, privacy, model provider, retention rule, or production change is requested. Until approval, do not check off T25/T26 or describe this draft PR as satisfying the original RED gate.
