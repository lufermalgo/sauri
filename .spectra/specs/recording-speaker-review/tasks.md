# Implementation Plan — Stored Recording Processing and Speaker Review

## Phase Summary

| Phase | Description | Tasks | Dependencies |
|---|---|---|---|
| 0 | Required independent pre-implementation security gate for voice-derived sample handling | T-20 | Must complete before T-13 starts; no voice-sample storage implementation before evidence |
| 1 | Required RED tests for backend invariants and web review | T-1–T-9 | None; independent test suites may run in parallel |
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

**Tracking:** Issue #234 · Card task_61bf056b1aec4081

**Files:** `backend/tests/speaker_review/test_review_state.py` (create)

**Action:** Add deterministic tests and Hypothesis property tests for correctness properties 1 and 2: recording one valid disposition changes only its target speaker item; review status is pending while any item lacks a valid disposition and complete iff all items have one. Generate varied review sizes and disposition combinations with at least 100 examples per property. Assert there is no request-level way to set completion directly.

**Acceptance evidence:** From `backend/`, `pytest tests/speaker_review/test_review_state.py` fails on the missing/incorrect review behavior before implementation; preserve the failing output in the issue/PR evidence. Hypothesis reports at least 100 examples for each property.

**Validation command:** `pytest tests/speaker_review/test_review_state.py` (from `backend/`).

**Dependencies:** None.

### T-2: RED — idempotent disposition writes

**Tracking:** Issue #235 · Card task_6b82254160eb4a98

**Files:** `backend/tests/speaker_review/test_disposition_idempotency.py` (create)

**Action:** Add deterministic tests and Hypothesis property tests for correctness property 9: same idempotency key and canonical request replays the saved result without a second sample/disposition mutation; reuse of a key with a different request hash conflicts; a different key with stale expected version conflicts without mutation; transaction failure rolls back disposition and identity-sample changes together. Generate varied retry sequences and request hashes with at least 100 examples per property.

**Acceptance evidence:** `pytest tests/speaker_review/test_disposition_idempotency.py` fails against the unimplemented contract; retain the failure output before GREEN work. Hypothesis reports at least 100 examples for each property.

**Validation command:** `pytest tests/speaker_review/test_disposition_idempotency.py` (from `backend/`).

**Dependencies:** None.

### T-3: RED — pending-review persistence and resume

**Tracking:** Issue #236 · Card task_08a5bfffd13e4fd9

**Files:** `backend/tests/speaker_review/test_review_resume.py` (create)

**Action:** Add tests for correctness property 3: a pending review retains completed speaker dispositions after leaving/reloading, returns only undisposed items as remaining, and does not request review again after the last disposition.

**Acceptance evidence:** `pytest tests/speaker_review/test_review_resume.py` fails for the missing behavior before implementation; record the output.

**Validation command:** `pytest tests/speaker_review/test_review_resume.py` (from `backend/`).

**Dependencies:** None.

### T-4: RED — same-owner identity matching and correction boundaries

**Tracking:** Issue #237 · Card task_3d9851b90af54464

**Files:** `backend/tests/speaker_review/test_identity_matching.py` (create)

**Action:** Add deterministic fake-matcher tests for correctness properties 5 and 6: only the current owner's active samples can be read/used; calibrated threshold and runner-up margin must both pass or result is uncertain; named/corrected samples inform later same-owner matches; a correction changes only the current item's association and preserves the wrongly suggested identity's samples; no global model is trained or modified. Include two distinct speaker items in one recording assigned to one identity and replay of either item's idempotency key without duplicate samples. Verify source-recording expiry/deletion removes its linked voice samples in the same cleanup transaction, while samples linked to other recordings remain.

**Acceptance evidence:** `pytest tests/speaker_review/test_identity_matching.py` fails on the missing identity boundary/behavior before implementation; record the output.

**Validation command:** `pytest tests/speaker_review/test_identity_matching.py` (from `backend/`).

**Dependencies:** None.

### T-5: RED — speaker excerpt correspondence and validation

**Tracking:** Issue #238 · Card task_8e1ed7b3a5f54922

**Files:** `backend/tests/speaker_review/test_excerpts.py` (create)

**Action:** Add tests for correctness property 7: each item resolves only to its target speaker's own recording excerpt; candidate selection follows the approved duration/VAD/tie-break ordering; reject out-of-bounds, undecodable, non-speech or other-speaker candidates; no review item is ready without a validated excerpt; playback failure does not substitute another excerpt or complete the item.

**Acceptance evidence:** `pytest tests/speaker_review/test_excerpts.py` fails on the missing excerpt contract before implementation; record the output.

**Validation command:** `pytest tests/speaker_review/test_excerpts.py` (from `backend/`).

**Dependencies:** None.

### T-6: RED — processing readiness, stage replay and finalizer recovery

**Tracking:** Issue #239 · Card task_c6ef43a295bb41a1

**Files:** `backend/tests/speaker_review/test_processing_readiness.py` (create)

**Action:** Add tests for correctness property 8: review becomes visible only after transcript, diarization, speaker set and validated excerpts for one revision commit ready together; duplicate stage/finalizer delivery creates no duplicate output or review and does not rerun a completed provider stage; an unexpired `(processing_revision_id, stage)` lease blocks duplicate provider execution, while an expired lease permits recovery; stage output, completion and outbox event commit atomically (failure rolls all three back); a finalizer failure after committed stages retries from persisted results.

**Acceptance evidence:** `pytest tests/speaker_review/test_processing_readiness.py` fails on the missing processing/readiness behavior before implementation; record the output.

**Validation command:** `pytest tests/speaker_review/test_processing_readiness.py` (from `backend/`).

**Dependencies:** None.

### T-7: RED — owner checks on legacy and review routes

**Tracking:** Issue #240 · Card task_0ac855a6ef27411e

**Files:** `backend/tests/meetings/test_speaker_review_ownership.py` (create)

**Action:** Add route integration tests for correctness property 10: transcript, diarization, review, disposition and excerpt reads/writes return not-found for another owner's meeting; owner ID is sourced from the authenticated principal; identity repository access and excerpt lookup are owner-scoped. Assert the review GET/PUT schemas and authenticated owner propagation match the approved cross-surface contract. Cover legacy routes so they cannot remain an existence-only bypass.

**Acceptance evidence:** `pytest tests/meetings/test_speaker_review_ownership.py` fails against the current ownership behavior before implementation; record the output.

**Validation command:** `pytest tests/meetings/test_speaker_review_ownership.py` (from `backend/`).

**Dependencies:** None.

### T-8: RED — revision consistency, admission races and migration

**Tracking:** Issue #241 · Card task_903b5c3055754303

**Files:** `backend/tests/speaker_review/test_processing_revisions.py` (create)

**Action:** Add tests for correctness property 11 and the revision-state boundary: migration backfills existing transcript/diarization rows to compatibility revision 1 and scopes uniqueness by meeting plus revision; legacy reads pin one revision; GET/admission locking is covered in both lock orders; only one concurrent initial candidate is admitted when active pointer is null; exact retries resume the in-flight revision; a pending active review rejects distinct reprocessing without mutation; a pre-marked ready current candidate can atomically activate and clear the in-flight pointer; non-current candidate activation and revision-qualified PUT/excerpt requests cannot displace/read/write another revision; no response combines revisions. Do not test stage-lease, outbox delivery or finalizer recovery here; T-6/T-15 cover those after the revision boundary exists. Cover complete and partial legacy records.

**Acceptance evidence:** `pytest tests/speaker_review/test_processing_revisions.py` fails on missing migration/revision behavior before implementation; record the output.

**Validation command:** `pytest tests/speaker_review/test_processing_revisions.py` (from `backend/`).

**Dependencies:** None.

### T-9: RED — transcript review UI states and actions

**Tracking:** Issue #242 · Card task_b1830561654c41e5

**Files:** `frontend/src/components/TranscriptView.test.tsx`

**Action:** Extend the existing component tests for the web requirements and correctness properties 1–4: pending/complete states; `Speaker N` for uncertain speakers; excerpt play request; explicit Confirm, Name and Correct actions; updating one item only; resume after remount; keyboard-operable controls; request failures leave the item pending and expose an error. Mock the authenticated meeting API at the typed API boundary.

**Acceptance evidence:** From `frontend/`, `npm run test -- --run src/components/TranscriptView.test.tsx` fails on the absent review UI before implementation; record the output.

**Validation command:** `npm run test -- --run src/components/TranscriptView.test.tsx` (from `frontend/`).

**Dependencies:** None.

## Phase 2: Backend GREEN Implementation

### T-10: GREEN — persist speaker review aggregate and derived item dispositions

**Tracking:** Issue #243 · Card task_5c10aed73c464472

**Files:** `backend/app/meetings/` review domain/service modules; `backend/app/infra/models.py`; migration under `backend/alembic/versions/`.

**Action:** Implement the recording/revision-scoped review aggregate and per-speaker immutable key/disposition state, with `named`, `corrected`, and `confirmed` validation. Derive pending/complete exclusively from item dispositions; persist one item's change without changing other items. Map the logical design fields onto existing SQLAlchemy/Alembic conventions.

**Acceptance evidence:** `pytest tests/speaker_review/test_review_state.py` passes, including proof that no caller can set completion directly.

**Validation command:** `pytest tests/speaker_review/test_review_state.py` (from `backend/`).

**Dependencies:** T-1.

### T-11: GREEN — make disposition persistence idempotent and atomic

**Tracking:** Issue #244 · Card task_25899bc56c6346bf

**Files:** `backend/app/meetings/` review service/repository modules; `backend/app/infra/models.py`; migration under `backend/alembic/versions/` as needed.

**Action:** Persist a disposition, identity-sample change and idempotency receipt in one transaction. Replay the original response for the same item/key/request hash; reject key/hash reuse and stale expected versions without mutation; roll back all associated writes on transaction failure.

**Acceptance evidence:** `pytest tests/speaker_review/test_disposition_idempotency.py` passes, including no duplicate sample on replay.

**Validation command:** `pytest tests/speaker_review/test_disposition_idempotency.py` (from `backend/`).

**Dependencies:** T-2, T-10.

### T-12: GREEN — persist and return review state for resume

**Tracking:** Issue #245 · Card task_5aaf06a24a074090

**Files:** `backend/app/meetings/` review service/repository modules.

**Action:** Implement active-review retrieval from persisted dispositions so reopening a pending review returns its saved decisions and only outstanding speaker items; completed review no longer requests a review. Do not add a revision-history UI.

**Acceptance evidence:** `pytest tests/speaker_review/test_review_resume.py` passes for partial and completed review reloads.

**Validation command:** `pytest tests/speaker_review/test_review_resume.py` (from `backend/`).

**Dependencies:** T-3, T-10.

### T-13: GREEN — implement owner-scoped identity matching and corrections

**Tracking:** Issue #246 · Card task_7ffcf8082710427b

**Files:** `backend/app/` identity matcher/repository modules; `backend/app/infra/models.py`; `backend/app/retention/` cleanup worker; migration under `backend/alembic/versions/` as needed.

**Action:** Before implementation begins, require independent security-review evidence resolving applicable handling for voice-derived identity samples; attach the review outcome to this task/issue, and do not proceed while a security blocker remains. Then implement the versioned embedding adapter and owner-scoped immutable samples, calibrated model-version threshold and runner-up margin checks, fail-closed uncertainty when uncalibrated, and target resolution that rejects cross-owner IDs. Named/corrected dispositions append source-review-item-keyed samples; correction changes only the current item's association and leaves source samples unchanged; confirmed writes no sample. Extend the existing recording expiry/deletion cleanup transaction to delete only samples linked to that source recording. No global training/model modification or new retention policy.

**Acceptance evidence:** `pytest tests/speaker_review/test_identity_matching.py` passes for ownership, uncertainty, correction lineage, same-recording multiple samples/replay, and source-linked sample deletion in the same cleanup transaction. Matching behavior without calibration remains `uncertain`. The independent security review record is attached and contains no unresolved blocker before implementation starts.

**Validation command:** `pytest tests/speaker_review/test_identity_matching.py` (from `backend/`).

**Dependencies:** T-4, T-10, T-11, T-20. The independent security review evidence is a blocking prerequisite; no voice-sample storage work starts before it.

### T-14: GREEN — derive and validate speaker-specific excerpts

**Tracking:** Issue #247 · Card task_486562bbb0d7425b

**Files:** `backend/app/` excerpt derivation/service modules; `backend/app/infra/` media boundary as needed.

**Action:** Derive candidates solely from target-speaker assigned segments, apply the approved duration/VAD/earliest-start ordering, validate bounds/decoding/speech activity/assignment, and persist an opaque recording- and speaker-bound excerpt reference. Do not expose object-store keys or substitute an excerpt. A missing valid excerpt keeps the revision not-ready and retryable.

**Acceptance evidence:** `pytest tests/speaker_review/test_excerpts.py` passes all candidate ranking, rejection, binding and playback-failure cases.

**Validation command:** `pytest tests/speaker_review/test_excerpts.py` (from `backend/`).

**Dependencies:** T-5.

### T-15: GREEN — gate readiness on durable pipeline stages and recover finalization

**Tracking:** Issue #248 · Card task_04a1d8c47e0241bf

**Files:** `backend/app/transcription/`; `backend/app/diarization/`; `backend/app/infra/` queue/outbox and stage persistence modules.

**Action:** After revision, review, identity-matching and excerpt boundaries exist, extend the async pipeline with conditional lease-based stage claims keyed by `(processing_revision_id, stage)`: an unexpired claim blocks duplicate provider execution, a completed stage replays its persisted result, and an expired claim permits recovery. Persist each stage output, completion state and outbox event in one transaction with uniqueness by revision/stage. Finalize only after both exact-revision stage outputs are complete; create review/excerpts once and activate only the current ready candidate atomically. Retry finalization from committed outputs without rerunning successful provider stages; do not expose partial reviews.

**Acceptance evidence:** `pytest tests/speaker_review/test_processing_readiness.py` passes for readiness barrier, unexpired/expired leases, atomic output/completion/outbox rollback, duplicate deliveries and finalizer recovery.

**Validation command:** `pytest tests/speaker_review/test_processing_readiness.py` (from `backend/`).

**Dependencies:** T-6, T-10, T-13, T-14, T-17.

### T-16: GREEN — enforce resource-owner checks on existing and new routes

**Tracking:** Issue #249 · Card task_2c4350aa34a94025

**Files:** `backend/app/meetings/router.py`; `backend/app/meetings/service.py`; meeting review/excerpt route modules.

**Action:** Require meeting ID and authenticated principal owner in transcript/diarization legacy handlers and every new review/disposition/excerpt operation. Derive owner only from the authenticated principal, scope all recording/identity/excerpt lookups, and return not-found for absent or non-owned meetings without leaking data.

**Acceptance evidence:** `pytest tests/meetings/test_speaker_review_ownership.py` passes for legacy and new routes, including cross-owner identity/excerpt attempts.

**Validation command:** `pytest tests/meetings/test_speaker_review_ownership.py` (from `backend/`).

**Dependencies:** T-7, T-10, T-11, T-12, T-13, T-14, T-17.

### T-17: GREEN — migrate and enforce exact processing revisions

**Tracking:** Issue #250 · Card task_2fe36f6fd508483b

**Files:** `backend/app/infra/models.py`; `backend/app/transcription/`; `backend/app/diarization/`; `backend/app/meetings/`; Alembic migration under `backend/alembic/versions/`.

**Action:** Add per-recording processing state and revision rows, backfill existing stage rows to compatibility revision 1, scope transcript/diarization uniqueness to `(meeting_id, processing_revision_id)`, and establish exact revision IDs on candidate admission, queue envelopes, repositories, legacy reads, review GET/PUT and excerpt operations. Serialize candidate admission and activation with the shared state-row lock. Maintain separate active and in-flight pointers, atomically activate only the current ready candidate, preserve a pending review against distinct reprocessing, and retain the in-flight slot through retryable failures. Provide the revision-aware stage/finalizer boundary; T-15 adds lease/outbox/recovery mechanics on that boundary.

**Acceptance evidence:** `pytest tests/speaker_review/test_processing_revisions.py` passes migration, legacy compatibility, admission/activation locking, concurrency, pending-review preservation, stale revision and no-mixed-read cases.

**Validation command:** `pytest tests/speaker_review/test_processing_revisions.py` (from `backend/`).

**Dependencies:** T-8, T-10, T-12, T-14.

## Phase 3: Web GREEN and Cross-Surface Validation

### T-18: GREEN — add per-speaker review to the transcript view

**Tracking:** Issue #251 · Card task_45143a5c381f471a

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

- RED suites T-1 through T-9 have no prerequisite edges and can be prepared independently.
- GREEN pairs: T-1 → T-10; T-2 → T-11; T-3 → T-12; T-4 → T-13; T-5 → T-14; T-6 → T-15; T-7 → T-16; T-8 → T-17; T-9 → T-18. These are mandatory RED-before-GREEN edges.
- T-20 → T-13 is the explicit pre-implementation security gate required by the design; voice-sample storage cannot start until the independent review evidence is recorded and blockers are resolved.
- T-10 → T-11/T-12/T-13/T-15/T-16/T-17 because those components require the persisted review model/service; T-11 → T-13/T-16 because identity sample writes share its transactional idempotency boundary and the route contract includes disposition writes; T-12 → T-16/T-17 because revision-aware review retrieval depends on persisted resume state; T-13 → T-15/T-16 because finalization creates attributed review items and route ownership covers identity repositories; T-14 → T-15/T-16/T-17 because readiness/finalization/revision activation and excerpt routes require validated excerpts. T-17 establishes revision state, exact-ID boundaries and atomic activation of an already-ready candidate before T-15 adds stage claims/outbox/recovery mechanics keyed to that revision, avoiding a schema/pipeline dependency cycle. T-16 waits for the review, identity, excerpt and revision contracts used by its full route tests. T-19 waits for all implementation tasks because it is whole-feature validation.
- No other edges are implied. In particular, unrelated RED suites and their implementation units remain parallel where the listed prerequisites permit.

## Traceability, Assumptions, and Open Implementation Dependencies

- Approved source: `.spectra/specs/recording-speaker-review/requirements.md` (Mira approved; blob `4ed34b66`, approved requirements PR #232); `.spectra/specs/recording-speaker-review/design.md` (Mira approved at commit `014d84c635201d037225b1e0f162264c45e2e2e8`); `PRODUCT_BASELINE.md` approved at commit `f5ff445fd508983740cd6b5a89c08adafcbb9295`, blob `c43cad6515b01a52037ad9cd4e09010a40477fb4` (approval annotation commit `b071a7c6d2c72613aa42543d15e47b81f4999077`).
- Assumptions: existing backend `pytest` and frontend `npm run test` commands are the configured validation entry points; named new test modules are introduced by the RED tasks. The exact embedding model/adapter remains an implementation dependency from the approved design; before calibration, matching must fail closed to uncertain. No threshold or margin value is invented here.
- No product decision is requested by this plan. The design-required independent security review is an explicit prerequisite to T-13; if it identifies a policy/product decision, T-13 remains blocked and the question is routed to Ansel. No security/privacy policy or retention guarantee is decided by this plan.
- Scope excludes capture/control, library, transcript editing, notes, summaries, general media synchronization, visible processing progress/errors, global voice modeling, cross-user sharing, authentication rollout, and retention guarantees.
