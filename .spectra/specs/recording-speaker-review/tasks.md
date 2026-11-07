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

**Files:** `backend/tests/integration/test_speaker_review_processing.py` (create)

**Action:** In `backend/tests/integration/test_speaker_review_processing.py`, exercise the design's existing async processing boundary across `backend/app/transcription/worker.py`, `backend/app/diarization/worker.py` and `backend/app/infra/` queue/outbox persistence. Assert correctness property 8: review becomes visible only after transcript, diarization, speaker set and validated excerpts for one revision commit ready together; duplicate stage/finalizer delivery creates no duplicate output/review or reruns a completed provider stage; an unexpired `(processing_revision_id, stage)` lease blocks duplicate execution while an expired lease permits recovery; stage output, completion and outbox event commit atomically; after finalization failure the existing outbox path retries from persisted results. Use synthetic provider/audio fixtures and the design-defined stage/revision transaction boundaries; do not invent worker function names or private test-only seams.

**Acceptance evidence:** `pytest tests/integration/test_speaker_review_processing.py` fails on missing processing/readiness behavior before implementation; retain the failure output.

**Validation command:** `pytest tests/integration/test_speaker_review_processing.py` (from `backend/`).

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

**Action:** In `backend/tests/meetings/test_speaker_review_revisions.py`, verify correctness property 11 through the design-defined `RecordingProcessingState` and `ProcessingRevision` persistence/lock boundary, `SpeakerReviewService.get_active_review(owner_id, meeting_id)`, legacy `GET .../transcript` and `GET .../diarization`, review `GET`, revision-qualified disposition `PUT`, and revision-qualified excerpt `GET` routes. Cover migration backfill to compatibility revision 1 and meeting+revision uniqueness; pin each read to one revision; test both GET/admission lock orders and single in-flight candidate admission, exact retries, pending-review admission rejection, exact-current-candidate activation/clear, and rejection of non-current activation or stale revision-qualified reads/writes. Include complete and partial legacy records and assert no response combines revisions. The design does not define a separate candidate-admission route or named coordinator function: exercise the existing processing admission boundary without adding a route, test helper, or function name. Do not test stage-lease, outbox delivery or finalizer recovery here; T-6/T-15 own those behaviors.

**Acceptance evidence:** `pytest tests/meetings/test_speaker_review_revisions.py` fails on missing migration/revision behavior before implementation; retain the failure output.

**Validation command:** `pytest tests/meetings/test_speaker_review_revisions.py` (from `backend/`).

**Dependencies:** None.

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

**Action:** After revision, review, identity-matching and excerpt boundaries exist, extend the async pipeline with conditional lease-based stage claims keyed by `(processing_revision_id, stage)`: an unexpired claim blocks duplicate provider execution, a completed stage replays its persisted result, and an expired claim permits recovery. Persist each stage output, completion state and outbox event in one transaction with uniqueness by revision/stage. Finalize only after both exact-revision stage outputs are complete; create review/excerpts once and activate only the current ready candidate atomically. Retry finalization from committed outputs without rerunning successful provider stages; do not expose partial reviews.

**Acceptance evidence:** `pytest tests/integration/test_speaker_review_processing.py` passes for readiness barrier, unexpired/expired leases, atomic output/completion/outbox rollback, duplicate deliveries and finalizer recovery.

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

**Action:** Add per-recording processing state and revision rows, backfill existing stage rows to compatibility revision 1, scope transcript/diarization uniqueness to `(meeting_id, processing_revision_id)`, and establish exact revision IDs on candidate admission, queue envelopes, repositories, legacy reads, review GET/PUT and excerpt operations. Serialize candidate admission and activation with the shared state-row lock. Maintain separate active and in-flight pointers, atomically activate only the current ready candidate, preserve a pending review against distinct reprocessing, and retain the in-flight slot through retryable failures. Provide the revision-aware stage/finalizer boundary; T-15 adds lease/outbox/recovery mechanics on that boundary.

**Acceptance evidence:** `pytest tests/meetings/test_speaker_review_revisions.py` passes migration, legacy compatibility, admission/activation locking, concurrency, pending-review preservation, stale revision and no-mixed-read cases.

**Validation command:** `pytest tests/meetings/test_speaker_review_revisions.py` (from `backend/`).

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

- Approved source: `.spectra/specs/recording-speaker-review/requirements.md` (Mira approved; blob `4ed34b66`, approved requirements PR #232); `.spectra/specs/recording-speaker-review/design.md` (Mira approved at commit `014d84c635201d037225b1e0f162264c45e2e2e8`); `PRODUCT_BASELINE.md` approved at commit `f5ff445fd508983740cd6b5a89c08adafcbb9295`, blob `c43cad6515b01a52037ad9cd4e09010a40477fb4` (approval annotation commit `b071a7c6d2c72613aa42543d15e47b81f4999077`).
- Assumptions: existing backend `pytest` and frontend `npm run test` commands are the configured validation entry points; named new test modules are introduced by the RED tasks. The exact embedding model/adapter remains an implementation dependency from the approved design; before calibration, matching must fail closed to uncertain. No threshold or margin value is invented here.
- No product decision is requested by this plan. The design-required independent security review is an explicit prerequisite to T-13; if it identifies a policy/product decision, T-13 remains blocked and the question is routed to Ansel. No security/privacy policy or retention guarantee is decided by this plan.
- Scope excludes capture/control, library, transcript editing, notes, summaries, general media synchronization, visible processing progress/errors, global voice modeling, cross-user sharing, authentication rollout, and retention guarantees.
