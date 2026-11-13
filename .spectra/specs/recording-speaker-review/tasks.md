# Implementation Plan — Stored Recording Processing and Speaker Review

## Phase Summary

| Phase | Description | Tasks | Dependencies |
|---|---|---|---|
| 0 | Required independent pre-implementation security gate for voice-derived sample handling | T-20 | Must complete before T-13 starts; no voice-sample storage implementation before evidence |
| 1 | Required RED tests for backend invariants and web review | T-1–T-9, T-7b | T-7b waits for T-10, T-12, T-13, T-14 and T-17 to establish persisted contracts |
| 2 | Backend GREEN implementation | T-10–T-17 | Each implementation task depends on its matching RED test and any additional prerequisites below |
| 3 | Web GREEN implementation and cross-surface verification | T-18–T-19 | T-18 depends on T-9; T-19 depends on T-10–T-18 |

The numbered order is for readability, not a launch schedule. Dependencies below are the actual DAG. Every RED task must be run and its expected failure recorded before its corresponding GREEN task begins. Backend commands run from `backend/`; frontend commands run from `frontend/`. Use synthetic audio, transcript, identity and owner fixtures only.

## Phase 0: Required Pre-implementation Security Gate

### T-20: GATE — independently review voice-derived sample handling before implementation

**Tracking:** Issue #253 · Card task_9dc19306fda14af2

**Files:** Security review evidence attached to the task issue/card; no source-code changes.

**Action:** Before T-13 begins, Zev independently reviews the planned voice-derived identity sample storage and source-recording cleanup against the approved design, records the applicable handling controls and any blockers, and identifies any unresolved policy/product decision for Ansel. Do not define new privacy policy or start T-13 storage work while a blocking finding or required owner-level decision remains unresolved.

**Acceptance evidence:** A written security review is linked from the task card; applicable controls are recorded and all blockers are resolved before T-13 starts. If a decision is needed, T-13 remains blocked pending Ansel's resolution.

**Validation:** Review-only gate; no code validation command applies. The required evidence is the independent security review record and its disposition.

**Dependencies:** None.

## Phase 1: Required RED Tests

### T-1: RED — review disposition isolation and derived completion

**Tracking:** Issue #234 · Card task_61bf056b1aec4081 · PR #255

**Files:** `backend/tests/meetings/test_speaker_review_state.py` (create)

**Action:** In `backend/tests/meetings/test_speaker_review_state.py`, add deterministic and Hypothesis tests for correctness properties 1 and 2 through the design-defined `SpeakerReviewService.record_disposition(...)` service boundary and the public PUT route/OpenAPI contract: one accepted disposition changes only its target item; review status is pending while any item lacks a disposition and complete iff all items have one. Generate varied review sizes and disposition combinations with at least 100 examples per property. Name the persisted service tests `domain_disposition_isolation` and `domain_derived_completion` so T-10 can target them. Keep the request-level schema assertion distinct as `test_review_put_schema_excludes_completion`; reject client-supplied completion state.

**Acceptance evidence:** From `backend/`, `pytest tests/meetings/test_speaker_review_state.py` fails on missing/incorrect service behavior and the unavailable/incorrect PUT schema before implementation; preserve the failing output in issue/PR evidence. Hypothesis reports at least 100 examples per property.

**Validation command:** `pytest tests/meetings/test_speaker_review_state.py` (from `backend/`).

**Dependencies:** None.

### T-2: RED — idempotent disposition writes

**Tracking:** Issue #235 · Card task_6b82254160eb4a98 · PR #258

**Files:** `backend/tests/meetings/test_speaker_review_disposition_idempotency.py` (create)

**Action:** In `backend/tests/meetings/test_speaker_review_disposition_idempotency.py`, add database-backed tests through the design-defined `SpeakerReviewService.record_disposition(...)` transaction boundary for correctness property 9: replaying the same idempotency key and canonical request returns its saved result without a second disposition/receipt mutation; reusing a key with a different request hash conflicts; a different key with stale `expected_version` conflicts without mutation; a failed transaction rolls back disposition and idempotency receipt together. Use Hypothesis to generate varied retry sequences and request hashes with at least 100 examples per property. Do not add synthetic mapping simulators, unapproved service functions, or production-only fault-injection hooks. Voice-sample rollback is verified by T-13 after its security gate; this task does not claim sample-persistence coverage.

**Acceptance evidence:** `pytest tests/meetings/test_speaker_review_disposition_idempotency.py` fails against the missing persisted service contract; retain the actual failing output before GREEN work. Hypothesis reports at least 100 examples per property.

**Validation command:** `pytest tests/meetings/test_speaker_review_disposition_idempotency.py` (from `backend/`).

**Dependencies:** None.

### T-3: RED — pending-review persistence and resume

**Tracking:** Issue #236 · Card task_08a5bfffd13e4fd9 · PR #397

**Files:** `backend/tests/meetings/test_speaker_review_resume.py` (create)

**Action:** In `backend/tests/meetings/test_speaker_review_resume.py`, test correctness property 3 through `SpeakerReviewService.get_active_review(owner_id, meeting_id)` and `SpeakerReviewService.record_disposition(...)`: a persisted pending review retains completed dispositions after a fresh service/database read, returns only undisposed items as remaining, and a completed review no longer requests review.

**Acceptance evidence:** `pytest tests/meetings/test_speaker_review_resume.py` fails for the missing persisted retrieval/resume behavior before implementation; record the output.

**Validation command:** `pytest tests/meetings/test_speaker_review_resume.py` (from `backend/`).

**Dependencies:** None.

### T-4: RED — same-owner identity matching and correction boundaries

**Tracking:** Issue #237 · Card task_3d9851b90af54464

**Files:** `backend/tests/diarization/test_speaker_identity_matching.py` and `backend/tests/retention/test_speaker_identity_sample_cleanup.py` (create).

**Action:** In the diarization test module, exercise the design-defined `SpeakerIdentityMatcher.match(owner_id, speaker_embedding)`, `resolve_target(owner_id, target_identity_id, label)`, and `apply_disposition(owner_id, current_identity_id, target_identity, speaker_embedding, disposition)` seams with deterministic synthetic embeddings: only the current owner's active samples are read; both calibrated threshold and runner-up margin must pass or the result is uncertain; named/corrected samples inform later same-owner matches; correction changes only the current item's association and preserves the wrong identity's samples; no global model is trained or modified. For persisted sample idempotency, call the design-defined `SpeakerReviewService.record_disposition(...)` service boundary: assign two speaker items in one recording to one identity, replay each item's disposition using that item's idempotency key, and assert each source-review-item-keyed sample is persisted once. Do not test replay through matcher methods, which do not own the disposition receipt/replay contract. In the retention test module, verify expiry/deletion through the existing `backend/app/retention/` cleanup worker boundary removes samples linked to that recording while preserving samples linked to other recordings; do not invent a cleanup API or private repository seam.

**Acceptance evidence:** `pytest tests/diarization/test_speaker_identity_matching.py tests/retention/test_speaker_identity_sample_cleanup.py` fails before implementation on missing identity isolation/matching, persisted `SpeakerReviewService.record_disposition(...)` replay without duplicate source-item samples, and source-recording cleanup behavior; record the output.

**Validation command:** `pytest tests/diarization/test_speaker_identity_matching.py tests/retention/test_speaker_identity_sample_cleanup.py` (from `backend/`).

**Dependencies:** None.

### T-5: RED — speaker excerpt correspondence and validation

**Tracking:** Issue #238 · Card task_8e1ed7b3a5f54922 · PR #400

**Status:** Done.

**Files:** `backend/tests/meetings/test_speaker_review_excerpts.py` (create)

**Action:** In `backend/tests/meetings/test_speaker_review_excerpts.py`, exercise the public `GET /api/v1/meetings/{meeting_id}/speaker-review/revisions/{revision_id}/speakers/{speaker_id}/excerpt` route and its existing authorized media/decoder boundary with synthetic audio. Assert each item resolves only its own recording/speaker excerpt; candidate selection follows the approved duration/VAD/tie-break order; out-of-bounds, undecodable, non-speech and other-speaker candidates are rejected; no review item becomes ready without a validated excerpt; playback failure does not substitute another excerpt or complete the item. Do not add a private repository seam or a QA API.

**Acceptance evidence:** `pytest tests/meetings/test_speaker_review_excerpts.py` fails on missing excerpt route/validation behavior before implementation; record the output.

**Validation command:** `pytest tests/meetings/test_speaker_review_excerpts.py` (from `backend/`).

**Dependencies:** None.

### T-6: RED — processing readiness, stage replay and finalizer recovery

**Tracking:** Issue #239 · Card task_c6ef43a295bb41a1 · PR #398

**Files:** `backend/tests/speaker_review/test_processing_readiness.py` (extend)

**Action:** Extend this synthetic-data test module against the exact approved private application-service seam `backend/app/transcription/processing_pipeline.py::ProcessingPipeline`, using only `process_stage(revision_id, stage)`, `finalize(revision_id)`, and `get_review(recording_id)` with persisted rows and injected deterministic async collaborators. In the isolated PostgreSQL test fixture, create a synthetic recording and an admitted processing revision, and set the recording's `in_flight_revision_id` to that revision before calling `process_stage` or `finalize`; a bare revision identifier or an unadmitted revision is not a valid fixture state. Verify that review is unavailable until transcript, diarization, speaker set, and validated excerpts for the same revision are committed; an unexpired revision/stage lease prevents duplicate provider execution and an expired lease permits recovery; and replaying a completed stage or finalizer produces no duplicate output/review and does not call its successful provider or identity matcher again. Cover a recognized synthetic matcher result, an uncertain result rendered as `Speaker N`, and matcher unavailability/failure: diarization still persists and completes, the attribution remains `Speaker N`, and the failure is observable through the existing processing logging/observability convention. Also assert atomic stage-output/completion/outbox persistence and recovery from finalizer failure using that isolated PostgreSQL fixture. Do not introduce `claim_stage`, `before_commit`, `count_*` production methods, other test-only hooks, or a second processing pipeline seam; inspect persistence through the test database and exercise only the three design-named methods. Keep imports inside test bodies as needed so pytest collects the RED cases before this new module/class exists; acceptance is not met by a collection error or skipped cases.

**Acceptance evidence:** `pytest tests/speaker_review/test_processing_readiness.py` collects and executes the required synthetic cases before implementation and records their expected failures; no case may be skipped or fail at collection. After GREEN, the same command passes for readiness, lease/replay/recovery, matcher outcomes and observability without rerunning completed providers/matcher.

**Validation command:** `pytest tests/speaker_review/test_processing_readiness.py` (from `backend/`).

**Dependencies:** None.

### T-7: RED — legacy ownership and review route/schema contracts

**Tracking:** Issue #240 · Card task_0ac855a6ef27411e

**Files:** `backend/tests/meetings/test_speaker_review_ownership.py`

**Action:** Keep this RED task limited to the existing tested contracts: legacy `GET /api/v1/meetings/{meeting_id}/transcript` and `GET /api/v1/meetings/{meeting_id}/diarization` hide another owner's meeting, and the public review `GET /api/v1/meetings/{meeting_id}/speaker-review`, `PUT /api/v1/meetings/{meeting_id}/speaker-review/revisions/{revision_id}/speakers/{speaker_id}`, and matching `GET .../excerpt` routes are declared with authenticated security and no caller-supplied `owner_id`. Assert the PUT request schema excludes `owner_id` and requires its idempotency header. Do not claim this task covers persisted ready reviews, foreign identity targets or validated excerpt ownership; those belong to T-7b. The test seam is this module's `test_legacy_read_routes_hide_another_owners_meeting`, `test_openapi_declares_authenticated_owner_scoped_review_contract`, `test_review_read_write_and_excerpt_hide_another_owners_meeting`, and `test_review_put_schema_excludes_caller_supplied_owner`, exercising the public routes and `app.openapi()` only.

**Acceptance evidence:** The recorded RED run produced seven failures: the two foreign-owner legacy reads returned 200 and the review route/schema assertions failed because the required routes/contracts were absent. Preserve that failure output as evidence; `git diff --check` passed. No production files were changed.

**Validation command:** `pytest tests/meetings/test_speaker_review_ownership.py` (from `backend/`).

**Dependencies:** None.

### T-7b: RED — persisted review identity and validated-excerpt owner isolation

**Tracking:** Issue #411 · Card task_eae564bc3a164d97

**Files:** `backend/tests/meetings/test_speaker_review_persisted_ownership.py` (create)

**Action:** Extend correctness property 10 with public-HTTP integration tests backed by persisted synthetic fixtures for a ready processing revision, review, speaker item, foreign owner's identity, and validated excerpt. Through authenticated requests to the review GET, revision-qualified disposition PUT, and revision-qualified excerpt GET routes listed in T-7, assert that a different principal cannot read the meeting owner's ready review or retrieve its excerpt, and that the meeting owner cannot assign an identity belonging to another principal; compare foreign-resource read responses with equivalent absent-resource responses and assert no mutation. Build the fixture using the persisted contracts established by T-10 (review/item), T-12 (review retrieval/resume), T-13 (owner-scoped identity/disposition), T-14 (validated excerpt), and T-17 (revision/active-ready state). Use synthetic media only and exercise excerpt validation/playback through the existing decoder boundary; do not add a private repository seam or a new public QA API. The test seam is this module's public HTTP requests to `GET /api/v1/meetings/{meeting_id}/speaker-review`, `PUT /api/v1/meetings/{meeting_id}/speaker-review/revisions/{revision_id}/speakers/{speaker_id}`, and `GET .../excerpt`, with persisted synthetic fixtures and the decoder boundary.

**Acceptance evidence:** `pytest tests/meetings/test_speaker_review_persisted_ownership.py` fails before T-16 on cross-owner access to a persisted ready review/excerpt and use of a foreign identity target; retain the concrete failing assertions and confirm the fixtures are synthetic. It passes after T-16 implements the corresponding owner checks.

**Validation command:** `pytest tests/meetings/test_speaker_review_persisted_ownership.py` (from `backend/`).

**Dependencies:** T-10, T-12, T-13, T-14, T-17. These implementation contracts are prerequisites for constructing a persisted ready revision/review/item, foreign identity, and validated excerpt without fabricating an API or repository seam.

### T-8: RED — revision consistency, admission races and migration

**Tracking:** Issue #241 · Card task_903b5c3055754303

**Files:** `backend/tests/meetings/test_speaker_review_revisions.py` (create)

**Action:** In `backend/tests/meetings/test_speaker_review_revisions.py`, exercise `backend/app/meetings/processing_revision_service.py::ProcessingRevisionService.admit_candidate` with a real PostgreSQL transaction and persisted synthetic rows, plus the existing `SpeakerReviewService.get_active_review(owner_id, meeting_id)`, legacy transcript/diarization GETs, review GET, revision-qualified disposition PUT, and excerpt GET. The admission method participates in the caller transaction; do not call `upload_recording` to test admission races, publish queue messages, or add an HTTP route, test helper, or production test seam. Cover migration backfill to compatibility revision 1 and meeting+revision uniqueness; pin reads/writes to exact revisions; test both GET/admission lock orders and concurrent distinct admission (exactly one candidate becomes in-flight), exact request retries, changed-fingerprint rejection, pending-review admission rejection, exact-current-candidate activation/clear, and rejection of stale/non-current reads, writes, or activation. Include complete and partial legacy records and assert no mixed-revision response. T-8 does not test stage leases, outbox dispatch/retry or finalizer recovery; those are T-6/T-15.

**Acceptance evidence:** `pytest tests/meetings/test_speaker_review_revisions.py` first fails on the intended missing migration/admission/revision behaviors against the pre-GREEN candidate. Record the failing assertions and confirm PostgreSQL fixture use; collection errors or SQLite dialect errors are not RED evidence. Preserve synthetic-only data.

**Validation command:** `pytest tests/meetings/test_speaker_review_revisions.py` (from `backend/`, with the approved PostgreSQL test fixture).

**Dependencies:** None. T-17/#250 is the mandatory GREEN successor and depends on this RED task; no production implementation begins until Nia records executable expected-failure evidence.

### T-9: RED — transcript review UI states and actions

**Tracking:** Issue #242 · Card task_b1830561654c41e5 · PR #413

**Status:** Done — PR #413 open for review.

**Files:** `frontend/src/components/TranscriptView.test.tsx`

**Action:** In `frontend/src/components/TranscriptView.test.tsx`, exercise the design-defined `TranscriptView` behavior and its typed API module boundary: pending/complete states; `Speaker N` for uncertain speakers; the revision-qualified excerpt GET request; explicit Confirm, Name and Correct actions through the revision-qualified disposition PUT; updating one item only; reload via the review GET after remount; keyboard-operable controls; and request failures that leave the item pending and expose an error. Mock only the authenticated meeting API at its typed API boundary.

**Acceptance evidence:** From `frontend/`, `npm run test -- --run src/components/TranscriptView.test.tsx` fails on the absent review UI before implementation; record the output.

**Validation command:** `npm run test -- --run src/components/TranscriptView.test.tsx` (from `frontend/`).

**Dependencies:** None.

## Phase 2: Backend GREEN Implementation

### T-10: GREEN — persist speaker review aggregate and derived item dispositions

**Tracking:** Issue #243 · Card task_5c10aed73c464472 · PR #257

**Files:** `backend/app/meetings/` review domain/service modules; `backend/app/infra/models.py`; migration under `backend/alembic/versions/`.

**Action:** Implement the recording/revision-scoped review aggregate and per-speaker immutable key/disposition state, with `named`, `corrected`, and `confirmed` validation. Derive pending/complete exclusively from item dispositions; persist one item's change without changing other items. Map the logical design fields onto existing SQLAlchemy/Alembic conventions.

**Acceptance evidence:** `pytest tests/meetings/test_speaker_review_state.py -k "domain_disposition_isolation or domain_derived_completion"` passes the domain isolation and derived-status tests, including at least 100 Hypothesis examples per property. This task does not claim the request-level OpenAPI assertion passes; T-16 must make that assertion pass.

**Validation command:** `pytest tests/meetings/test_speaker_review_state.py -k "domain_disposition_isolation or domain_derived_completion"` (from `backend/`).

**Dependencies:** T-1.

### T-11: GREEN — make disposition persistence idempotent and atomic

**Tracking:** Issue #244 · Card task_25899bc56c6346bf · PR #322

**Status:** Done — PR #322 open for review.

**Files:** `backend/app/meetings/` review service/repository modules; `backend/app/infra/models.py`; migration under `backend/alembic/versions/` as needed.

**Action:** Implement persistent idempotent disposition and receipt writes through `SpeakerReviewService.record_disposition(...)`, with same-key/same-request replay, key/hash conflict, stale-version conflict and atomic rollback of the disposition and receipt in one database transaction. Do not persist voice samples here; preserve the transaction boundary and idempotency contract that T-13 extends after its security gate to include voice-sample writes atomically. Do not add test-only production fault-injection hooks.

**Acceptance evidence:** `pytest tests/meetings/test_speaker_review_disposition_idempotency.py` passes for persisted disposition/receipt replay, conflict and rollback behavior. Sample-write atomicity, including rollback across disposition, receipt and sample, is implemented and validated by T-13 after T-20 clears; T-11 does not claim it.

**Validation command:** `pytest tests/meetings/test_speaker_review_disposition_idempotency.py` (from `backend/`).

**Dependencies:** T-2, T-10. T-11 may proceed before T-20 only for disposition/receipt persistence; it must not add voice-sample storage. T-13 depends on T-11 and T-20, and extends the transaction with voice-sample persistence only after the security gate is resolved.

### T-12: GREEN — persist and return review state for resume

**Tracking:** Issue #245 · Card task_5aaf06a24a074090 · PR #418

**Status:** Done — PR #418 open for review.

**Files:** `backend/app/meetings/` review service/repository modules.

**Action:** Implement active-review retrieval from persisted dispositions so reopening a pending review returns its saved decisions and only outstanding speaker items; completed review no longer requests a review. Do not add a revision-history UI.

**Acceptance evidence:** `pytest tests/meetings/test_speaker_review_resume.py` passes for partial and completed review reloads.

**Validation command:** `pytest tests/meetings/test_speaker_review_resume.py` (from `backend/`).

**Dependencies:** T-3, T-10.

### T-13: GREEN — implement owner-scoped identity matching and corrections

**Tracking:** Issue #246 · Card task_7ffcf8082710427b

**Files:** `backend/app/` identity matcher/repository modules; `backend/app/infra/models.py`; `backend/app/retention/` cleanup worker; migration under `backend/alembic/versions/` as needed.

**Action:** Before implementation begins, require independent security-review evidence resolving applicable handling for voice-derived identity samples; attach the review outcome to this task/issue, and do not proceed while a security blocker remains. Then implement the versioned embedding adapter and owner-scoped immutable samples, calibrated model-version threshold and runner-up margin checks, fail-closed uncertainty when uncalibrated, and target resolution that rejects cross-owner IDs. Named/corrected dispositions append source-review-item-keyed samples; correction changes only the current item's association and leaves source samples unchanged; confirmed writes no sample. Extend the existing recording expiry/deletion cleanup transaction to delete only samples linked to that source recording. No global training/model modification or new retention policy.

**Acceptance evidence:** `pytest tests/diarization/test_speaker_identity_matching.py tests/retention/test_speaker_identity_sample_cleanup.py` passes for ownership, uncertainty, correction lineage, same-recording multiple samples/replay, and source-linked sample deletion in the same cleanup transaction. The diarization suite also exercises `SpeakerReviewService.record_disposition(...)` through its transaction boundary, using test-only database/session instrumentation to force rollback at sample insertion (not a production fault-injection API), then rereads in a fresh session and asserts disposition, idempotency receipt, and voice-sample state are unchanged. Matching without calibration remains `uncertain`. The independent security review record is attached and contains no unresolved blocker before implementation starts.

**Validation command:** `pytest tests/diarization/test_speaker_identity_matching.py tests/retention/test_speaker_identity_sample_cleanup.py` (from `backend/`).

**Dependencies:** T-4, T-10, T-11, T-20. The independent security review evidence is a blocking prerequisite; no voice-sample storage work starts before it.

### T-14: GREEN — derive and validate speaker-specific excerpts

**Tracking:** Issue #247 · Card task_486562bbb0d7425b · PR #401 · Status: done (QA and security passed; PR open for review)

**Files:** `backend/app/` excerpt derivation/service modules; `backend/app/infra/` media boundary as needed.

**Action:** Derive candidates solely from target-speaker assigned segments, apply the approved duration/VAD/earliest-start ordering, validate bounds/decoding/speech activity/assignment, and persist an opaque recording- and speaker-bound excerpt reference. Do not expose object-store keys or substitute an excerpt. A missing valid excerpt keeps the revision not-ready and retryable.

**Acceptance evidence:** `pytest tests/meetings/test_speaker_review_excerpts.py` passes all candidate ranking, rejection, binding and playback-failure cases.

**Validation command:** `pytest tests/meetings/test_speaker_review_excerpts.py` (from `backend/`).

**Dependencies:** T-5.

### T-15: GREEN — gate readiness on durable pipeline stages and recover finalization

**Tracking:** Issue #248 · Card task_04a1d8c47e0241bf

**Files:** `backend/app/transcription/`; `backend/app/diarization/`; `backend/app/infra/` queue/outbox and stage persistence modules.

**Action:** Implement the design-defined `backend/app/transcription/processing_pipeline.py::ProcessingPipeline`, wired through the existing worker startup in `backend/app/worker.py`. `process_stage(revision_id, stage)` must resolve and claim the exact admitted revision/stage, skip duplicate execution under an unexpired lease, replay completed output, and on an acquired/expired claim invoke only the selected injected provider. Persist exact-revision stage output, completion and outbox event atomically. Implement `finalize(revision_id)` to return not-ready unless both exact-revision stages are committed and the revision remains the in-flight candidate; validate excerpts, create the review once and atomically activate/clear that candidate. Retry from committed outputs without rerunning successful providers; never expose partial review data. Dispatch/retry the `processing_revision_admitted` outbox event only after T-17's admission transaction commits. Do not implement candidate admission/persistence, change `upload_recording`, add routes, or add test-only production seams; those are outside T-15.

**Acceptance evidence:** `pytest tests/integration/test_speaker_review_processing.py` passes readiness barrier, exact-revision stage dispatch, unexpired/expired leases, completed-stage replay, atomic output/completion/outbox rollback, duplicate delivery and finalizer recovery. Record synthetic fixture provenance and exact candidate SHA.

**Validation command:** `pytest tests/integration/test_speaker_review_processing.py` (from `backend/`).

**Dependencies:** T-6, T-10, T-13, T-14, T-17.

### B-1: Security remediation — enforce commercial authorization and ownership on transcript/diarization reads

**Tracking:** Issue #478 · Card task_60e40e6776b74228 · PR #480 · Status: done (QA and security passed)

**Files:** `backend/app/meetings/router.py`; transcript and diarization route tests.

**Action:** Enforce commercial-role authorization and meeting ownership on the existing transcript and diarization GET routes before protected reads. Return 403 for non-commercial users; return 404 for missing or non-owned meetings; audit both denial paths. Preserve the API response contract.

**Acceptance evidence:** Targeted tests passed (12); Nia recorded QA `PASS` and Zev recorded `NO_ACTIONABLE_FINDINGS` on the exact candidate. Full backend pytest remains blocked during collection by the missing `app.transcription.processing_pipeline`; Ruff was unavailable in the implementation environment.

### B-2: Security remediation — authorize meeting detail, join, rename, and delete routes

**Tracking:** Issue #504 · Card task_138287b156e54fa0 · PR #691 · Status: QA PASS and security NO_ACTIONABLE_FINDINGS on candidate `18432e379868690b911af95b1f3e4ab10dd9e395`

**Files:** `backend/app/meetings/router.py`; `backend/tests/meetings/test_meeting_route_authorization.py`; `backend/tests/meetings/test_router_exception_chaining.py`; `.spectra/specs/recording-speaker-review/tasks.md`.

**Action:** Apply the shared commercial-role and meeting-owner authorization helper to GET `/{meeting_id}`, POST `/{meeting_id}/request-join`, PATCH `/{meeting_id}`, and DELETE `/{meeting_id}`. Audit denials and preserve successful owner responses and the request-join 409 for non-queued meetings.

**Acceptance evidence:** RED: against the pre-B-2 router, unauthorized GET and request-join returned 200, while PATCH/DELETE applied neither commercial-role checks nor denial audit (9 failing tests; 8 before the two added assertions). GREEN: 73 passed in `tests/meetings`, with one pre-existing environmental failure, `test_signed_playback_source_supports_range_and_frontend_cors`, requiring `OBJECT_STORE_ENDPOINT`; Ruff and mypy were clean. Nia recorded QA `PASS` and Zev `NO_ACTIONABLE_FINDINGS` on exact candidate `18432e379868690b911af95b1f3e4ab10dd9e395`. Coverage confirms denial paths never connect the broker, and unknown-ID request-join returns a non-disclosing 404 without echoing the ID and writes exactly one `denied` audit row. Deliberate privacy change: an unknown ID now returns 404 instead of 409 to prevent existence probing; the owner's 409 for a non-queued meeting is unchanged. The full backend suite remains blocked during collection by missing `app.transcription.processing_pipeline`.

### T-16: GREEN — enforce resource-owner checks on existing and new routes

**Tracking:** Issue #249 · Card task_2c4350aa34a94025

**Files:** `backend/app/meetings/router.py`; `backend/app/meetings/service.py`; meeting review/excerpt route modules.

**Action:** Require meeting ID and authenticated principal owner in transcript/diarization legacy handlers and every new review/disposition/excerpt operation. Derive owner only from the authenticated principal, scope all recording/identity/excerpt lookups, and return not-found for absent or non-owned meetings without leaking data. Keep the OpenAPI route/schema and legacy-owner assertions in T-7 distinct from persisted ready-state identity/excerpt ownership integration coverage in T-7b.

**Acceptance evidence:** `pytest tests/meetings/test_speaker_review_ownership.py tests/meetings/test_speaker_review_persisted_ownership.py` passes the T-7 legacy ownership and route/schema assertions plus T-7b persisted ready-review, foreign-identity and validated-excerpt owner-isolation assertions. The request-level OpenAPI PUT schema assertion `test_review_put_schema_excludes_completion` in `backend/tests/meetings/test_speaker_review_state.py` also passes and proves completion state cannot be supplied by a caller; this closes the RED assertion retained by T-1.

**Validation command:** `pytest tests/meetings/test_speaker_review_ownership.py tests/meetings/test_speaker_review_persisted_ownership.py tests/meetings/test_speaker_review_state.py` (from `backend/`).

**Dependencies:** T-7, T-7b, T-10, T-11, T-12, T-13, T-14, T-17.

### T-17: GREEN — migrate and enforce exact processing revisions

**Tracking:** Issue #250 · Card task_2fe36f6fd508483b

**Files:** `backend/app/infra/models.py`; `backend/app/transcription/`; `backend/app/diarization/`; `backend/app/meetings/`; Alembic migration under `backend/alembic/versions/`.

**Action:** Implement the exact persistence and admission contract exercised by T-8. Add per-recording processing state/revision rows; backfill legacy stage rows to compatibility revision 1; replace meeting-only transcript/diarization uniqueness with `(meeting_id, processing_revision_id)` uniqueness; and persist exact revision IDs for worker events, repository writes, legacy reads, review GET/PUT and excerpt operations. Implement `backend/app/meetings/processing_revision_service.py::ProcessingRevisionService(session).admit_candidate(owner_id, recording_id, request_id, request_fingerprint)` and call it from `backend/app/ingestion/service.py::process_ingestion` inside the existing `upload_recording` transaction after a recording row is created or an idempotent request is resolved. Lock the processing-state row; exact retries return the same revision only for the same fingerprint; changed replays, concurrent distinct in-flight candidates, and distinct requests while a review is pending are rejected without mutation. Allocate one revision and persist its `processing_revision_admitted` outbox event in that transaction. Keep `active_processing_revision_id` and `in_flight_revision_id` distinct; activate and clear only the exact current ready candidate atomically. T-17 owns the admission service/state/revision persistence and event record; T-15 owns post-commit outbox dispatch/retry, stage leases, stage output persistence and finalizer recovery. Do not add a new HTTP route or test-only admission seam.

**Acceptance evidence:** `pytest tests/meetings/test_speaker_review_revisions.py` passes PostgreSQL-backed migration/backfill and uniqueness, both GET/admission lock orders, concurrent distinct admission, exact retry/fingerprint rejection, pending-review protection, atomic exact-current activation, stale revision rejection and no-mixed-read cases. No required PostgreSQL case may be skipped; record the configured local high-port test database and exact candidate SHA.

**Validation command:** `pytest tests/meetings/test_speaker_review_revisions.py` (from `backend/`, with `SAURI_T8_TEST_DATABASE_URL` set to the isolated local high-port PostgreSQL test database).

**Independent migration reconciliation (#250, PR #885; supersedes alternative PR #883):** Current main adds `014_meeting_summaries_templates` alongside this candidate's `014_processing_revisions`, both descending from 013. The technical follow-up copies the existing summary migration unchanged and adds a no-op `015_merge_processing_summaries` with both parents, plus isolated PostgreSQL regression `backend/tests/meetings/test_processing_summary_merge.py` for both upgrade orders, retained rows, rollback to the original 014 parent and re-upgrade. The linear-parent rewrite in #883 cannot migrate a database already stamped `014_processing_revisions` to summary schema: Alembic reports that revision as current while `summary_templates` remains absent; it must not replace the original published parent. It does not dispatch the admission outbox, add stage leases, activate speaker review, or implement T-15. The T-20 #253 → T-13 #246 → T-15 #248 privacy gate remains binding; the earlier T-15 PR #884 was closed unmerged.

**Dependencies:** T-8, T-10, T-12, T-14.

## Phase 3: Web GREEN and Cross-Surface Validation

### T-18: GREEN — add per-speaker review to the transcript view

**Tracking:** Issue #251 · Card task_45143a5c381f471a · PR #521

**Status:** Done — PR #521 open for review.

**Files:** `frontend/src/components/TranscriptView.tsx`; `frontend/src/api.ts`; `frontend/src/components/TranscriptView.test.tsx`.

**Action:** Integrate typed meeting review GET, per-speaker disposition PUT and opaque excerpt playback operations in the existing transcript view. Render uncertain speakers as `Speaker N`, explicit Confirm/Name/Correct controls, pending/complete state and one-item updates; reload server state on remount; keep controls keyboard-operable and show failures without advancing an item locally.

**Acceptance evidence:** `npm run test -- --run src/components/TranscriptView.test.tsx` passes all review tests, including remount and error cases.

**Validation command:** `npm run test -- --run src/components/TranscriptView.test.tsx` (from `frontend/`).

**Dependencies:** T-9.

### T-19: Verify feature package validation and cross-surface contract

**Tracking:** Issue #252 · Card task_4fb9ede796454770

**Files:** backend and frontend test/configuration surfaces touched by this plan.

**Action:** Run the approved configured backend and frontend validation commands; add/fix only test wiring needed to validate the implemented API schema/route contract, authenticated owner propagation and review response compatibility. Do not broaden feature scope or alter product requirements.

**Acceptance evidence:** From `backend/`, `pytest`, `ruff check .`, and `mypy .` pass; from `frontend/`, `npm run test`, `npm run typecheck`, and `npm run build` pass. Record complete command output in the implementation PR. If any environment prerequisite prevents a command, document the exact failure as blocked rather than skipping it.

**Validation command:** `pytest && ruff check . && mypy .` (from `backend/`); `npm run test && npm run typecheck && npm run build` (from `frontend/`).

**Dependencies:** T-10, T-11, T-12, T-13, T-14, T-15, T-16, T-17, T-18.

## Dependency DAG and Rationale

- RED suites T-1 through T-9 have no prerequisite edges and can be prepared independently. T-7b is a separate RED suite that requires persisted fixture contracts from T-10, T-12, T-13, T-14 and T-17; it must not be scheduled before those prerequisites.
- GREEN pairs: T-1 → T-10; T-2 → T-11; T-3 → T-12; T-4 → T-13; T-5 → T-14; T-6 → T-15; T-7 → T-16; T-8 → T-17; T-9 → T-18. T-7b → T-16 is an additional mandatory RED-before-GREEN edge for persisted ready-review, identity-target and validated-excerpt owner isolation.
- T-20 → T-13 is the explicit pre-implementation security gate required by the design; voice-sample storage cannot start until the independent review evidence is recorded and blockers are resolved.
- T-10 → T-7b/T-11/T-12/T-13/T-15/T-16/T-17 because T-7b requires persisted review/item fixtures and those components require the persisted review model/service; T-11 → T-13/T-16 because T-13 extends T-11's persistent disposition/receipt transaction to include voice-sample writes only after T-20 clears, and the route contract includes disposition writes; T-12 → T-7b/T-16/T-17 because persisted review retrieval/resume state is needed for T-7b fixtures and revision-aware retrieval; T-13 → T-7b/T-15/T-16 because owner-scoped identity/disposition persistence is needed by T-7b and finalization; T-14 → T-7b/T-15/T-16/T-17 because validated excerpt persistence is needed by T-7b and readiness/finalization/revision activation; T-17 → T-7b because a persisted active ready revision is needed by its fixtures. T-17 establishes revision state, exact-ID boundaries and atomic activation of an already-ready candidate before T-15 adds stage claims/outbox/recovery mechanics keyed to that revision, avoiding a schema/pipeline dependency cycle. T-16 waits for T-7 and T-7b plus the review, identity, excerpt and revision contracts used by its full route tests. T-19 waits for all implementation tasks because it is whole-feature validation.
- No other edges are implied. In particular, unrelated RED suites and their implementation units remain parallel where the listed prerequisites permit.

## Traceability, Assumptions, and Open Implementation Dependencies

- Approved source: `.spectra/specs/recording-speaker-review/requirements.md` (Mira approved; blob `4ed34b66`, approved requirements PR #232); `.spectra/specs/recording-speaker-review/design.md` (Mira approved at commit `014d84c635201d037225b1e0f162264c45e2e2e8`) plus the additive admission/pipeline seam clarification in PR #589, Mira-approved commit `401d22bb2ce98c1feb0ef97aeb626a37f47f2ea0`, blob `02900d06c9481dda5920df5f2ba4875a8c551520` (open, not merged); `PRODUCT_BASELINE.md` approved at commit `f5ff445fd508983740cd6b5a89c08adafcbb9295`, blob `c43cad6515b01a52037ad9cd4e09010a40477fb4` (approval annotation commit `b071a7c6d2c72613aa42543d15e47b81f4999077`).
- Assumptions: existing backend `pytest` and frontend `npm run test` commands are the configured validation entry points; named new test modules are introduced by the RED tasks. The exact embedding model/adapter remains an implementation dependency from the approved design; before calibration, matching must fail closed to uncertain. No threshold or margin value is invented here.
- No product decision is requested by this plan. The design-required independent security review is an explicit prerequisite to T-13; if it identifies a policy/product decision, T-13 remains blocked and the question is routed to Ansel. No security/privacy policy or retention guarantee is decided by this plan.
- Scope excludes capture/control, library, transcript editing, notes, summaries, general media synchronization, visible processing progress/errors, global voice modeling, cross-user sharing, authentication rollout, and retention guarantees.
