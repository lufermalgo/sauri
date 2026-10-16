# Implementation Plan — Stored Recording Processing and Speaker Review

## Phase Summary

| Phase | Description | Tasks | Dependencies |
|---|---|---|---|
| 1 | Required RED tests for backend invariants and web review | T-1–T-9 | None; independent test suites may run in parallel |
| 2 | Backend GREEN implementation | T-10–T-17 | Each implementation task depends on its matching RED test; T-17 also depends on T-14 |
| 3 | Web GREEN implementation and cross-surface verification | T-18–T-19 | T-18 depends on T-9; T-19 depends on T-10–T-18 |

The numbered order is for readability, not a launch schedule. Dependencies below are the actual DAG. Every RED task must be run and its expected failure recorded before its corresponding GREEN task begins. Backend commands run from `backend/`; frontend commands run from `frontend/`. Use synthetic audio, transcript, identity and owner fixtures only.

## Phase 1: Required RED Tests

### T-1: RED — review disposition isolation and derived completion

**Files:** `backend/tests/speaker_review/test_review_state.py` (create)

**Action:** Add tests for correctness properties 1 and 2: recording one valid disposition changes only its target speaker item; review status is pending while any item lacks a valid disposition and complete iff all items have one. Assert there is no request-level way to set completion directly.

**Acceptance evidence:** From `backend/`, `pytest tests/speaker_review/test_review_state.py` fails on the missing/incorrect review behavior before implementation; preserve the failing output in the issue/PR evidence.

**Validation command:** `pytest tests/speaker_review/test_review_state.py` (from `backend/`).

**Dependencies:** None.

### T-2: RED — idempotent disposition writes

**Files:** `backend/tests/speaker_review/test_disposition_idempotency.py` (create)

**Action:** Add tests for correctness property 9: same idempotency key and canonical request replays the saved result without a second sample/disposition mutation; reuse of a key with a different request hash conflicts; a different key with stale expected version conflicts without mutation; transaction failure rolls back disposition and identity-sample changes together.

**Acceptance evidence:** `pytest tests/speaker_review/test_disposition_idempotency.py` fails against the unimplemented contract; retain the failure output before GREEN work.

**Validation command:** `pytest tests/speaker_review/test_disposition_idempotency.py` (from `backend/`).

**Dependencies:** None.

### T-3: RED — pending-review persistence and resume

**Files:** `backend/tests/speaker_review/test_review_resume.py` (create)

**Action:** Add tests for correctness property 3: a pending review retains completed speaker dispositions after leaving/reloading, returns only undisposed items as remaining, and does not request review again after the last disposition.

**Acceptance evidence:** `pytest tests/speaker_review/test_review_resume.py` fails for the missing behavior before implementation; record the output.

**Validation command:** `pytest tests/speaker_review/test_review_resume.py` (from `backend/`).

**Dependencies:** None.

### T-4: RED — same-owner identity matching and correction boundaries

**Files:** `backend/tests/speaker_review/test_identity_matching.py` (create)

**Action:** Add deterministic fake-matcher tests for correctness properties 5 and 6: only the current owner's active samples can be read/used; calibrated threshold and runner-up margin must both pass or result is uncertain; named/corrected samples inform later same-owner matches; a correction changes only the current item's association and preserves the wrongly suggested identity's samples; no global model is trained or modified. Include two distinct speaker items in one recording assigned to one identity and replay of either item's idempotency key without duplicate samples.

**Acceptance evidence:** `pytest tests/speaker_review/test_identity_matching.py` fails on the missing identity boundary/behavior before implementation; record the output.

**Validation command:** `pytest tests/speaker_review/test_identity_matching.py` (from `backend/`).

**Dependencies:** None.

### T-5: RED — speaker excerpt correspondence and validation

**Files:** `backend/tests/speaker_review/test_excerpts.py` (create)

**Action:** Add tests for correctness property 7: each item resolves only to its target speaker's own recording excerpt; candidate selection follows the approved duration/VAD/tie-break ordering; reject out-of-bounds, undecodable, non-speech or other-speaker candidates; no review item is ready without a validated excerpt; playback failure does not substitute another excerpt or complete the item.

**Acceptance evidence:** `pytest tests/speaker_review/test_excerpts.py` fails on the missing excerpt contract before implementation; record the output.

**Validation command:** `pytest tests/speaker_review/test_excerpts.py` (from `backend/`).

**Dependencies:** None.

### T-6: RED — processing readiness, stage replay and finalizer recovery

**Files:** `backend/tests/speaker_review/test_processing_readiness.py` (create)

**Action:** Add tests for correctness property 8: review becomes visible only after transcript, diarization, speaker set and validated excerpts for one revision commit ready together; duplicate stage/finalizer delivery creates no duplicate output or review and does not rerun a completed provider stage; a finalizer failure after committed stages retries from persisted results.

**Acceptance evidence:** `pytest tests/speaker_review/test_processing_readiness.py` fails on the missing processing/readiness behavior before implementation; record the output.

**Validation command:** `pytest tests/speaker_review/test_processing_readiness.py` (from `backend/`).

**Dependencies:** None.

### T-7: RED — owner checks on legacy and review routes

**Files:** `backend/tests/meetings/test_speaker_review_ownership.py` (create)

**Action:** Add route integration tests for correctness property 10: transcript, diarization, review, disposition and excerpt reads/writes return not-found for another owner's meeting; owner ID is sourced from the authenticated principal; identity repository access and excerpt lookup are owner-scoped. Assert the review GET/PUT schemas and authenticated owner propagation match the approved cross-surface contract. Cover legacy routes so they cannot remain an existence-only bypass.

**Acceptance evidence:** `pytest tests/meetings/test_speaker_review_ownership.py` fails against the current ownership behavior before implementation; record the output.

**Validation command:** `pytest tests/meetings/test_speaker_review_ownership.py` (from `backend/`).

**Dependencies:** None.

### T-8: RED — revision consistency, admission races and migration

**Files:** `backend/tests/speaker_review/test_processing_revisions.py` (create)

**Action:** Add tests for correctness property 11 and the approved revision design: migration backfills existing transcript/diarization rows to compatibility revision 1 and scopes uniqueness by meeting plus revision; legacy reads pin one revision; GET/admission locking is covered in both lock orders; only one concurrent initial candidate is admitted when active pointer is null; exact retries resume the in-flight revision; a pending active review rejects distinct reprocessing without mutation; completed review permits candidate processing and atomic activation; stale/non-current finalizers and revision-qualified PUT/excerpt requests cannot displace/read/write another revision; no response combines revisions. Cover complete and partial legacy records.

**Acceptance evidence:** `pytest tests/speaker_review/test_processing_revisions.py` fails on missing migration/revision behavior before implementation; record the output.

**Validation command:** `pytest tests/speaker_review/test_processing_revisions.py` (from `backend/`).

**Dependencies:** None.

### T-9: RED — transcript review UI states and actions

**Files:** `frontend/src/components/TranscriptView.test.tsx`

**Action:** Extend the existing component tests for the web requirements and correctness properties 1–4: pending/complete states; `Speaker N` for uncertain speakers; excerpt play request; explicit Confirm, Name and Correct actions; updating one item only; resume after remount; keyboard-operable controls; request failures leave the item pending and expose an error. Mock the authenticated meeting API at the typed API boundary.

**Acceptance evidence:** From `frontend/`, `npm run test -- --run src/components/TranscriptView.test.tsx` fails on the absent review UI before implementation; record the output.

**Validation command:** `npm run test -- --run src/components/TranscriptView.test.tsx` (from `frontend/`).

**Dependencies:** None.

## Phase 2: Backend GREEN Implementation

### T-10: GREEN — persist speaker review aggregate and derived item dispositions

**Files:** `backend/app/meetings/` review domain/service modules; `backend/app/infra/models.py`; migration under `backend/alembic/versions/`.

**Action:** Implement the recording/revision-scoped review aggregate and per-speaker immutable key/disposition state, with `named`, `corrected`, and `confirmed` validation. Derive pending/complete exclusively from item dispositions; persist one item's change without changing other items. Map the logical design fields onto existing SQLAlchemy/Alembic conventions.

**Acceptance evidence:** `pytest tests/speaker_review/test_review_state.py` passes, including proof that no caller can set completion directly.

**Validation command:** `pytest tests/speaker_review/test_review_state.py` (from `backend/`).

**Dependencies:** T-1.

### T-11: GREEN — make disposition persistence idempotent and atomic

**Files:** `backend/app/meetings/` review service/repository modules; `backend/app/infra/models.py`; migration under `backend/alembic/versions/` as needed.

**Action:** Persist a disposition, identity-sample change and idempotency receipt in one transaction. Replay the original response for the same item/key/request hash; reject key/hash reuse and stale expected versions without mutation; roll back all associated writes on transaction failure.

**Acceptance evidence:** `pytest tests/speaker_review/test_disposition_idempotency.py` passes, including no duplicate sample on replay.

**Validation command:** `pytest tests/speaker_review/test_disposition_idempotency.py` (from `backend/`).

**Dependencies:** T-2, T-10.

### T-12: GREEN — persist and return review state for resume

**Files:** `backend/app/meetings/` review service/repository modules.

**Action:** Implement active-review retrieval from persisted dispositions so reopening a pending review returns its saved decisions and only outstanding speaker items; completed review no longer requests a review. Do not add a revision-history UI.

**Acceptance evidence:** `pytest tests/speaker_review/test_review_resume.py` passes for partial and completed review reloads.

**Validation command:** `pytest tests/speaker_review/test_review_resume.py` (from `backend/`).

**Dependencies:** T-3, T-10.

### T-13: GREEN — implement owner-scoped identity matching and corrections

**Files:** `backend/app/` identity matcher/repository modules; `backend/app/infra/models.py`; migration under `backend/alembic/versions/` as needed.

**Action:** Implement versioned embedding adapter and owner-scoped immutable samples, calibrated model-version threshold and runner-up margin checks, fail-closed uncertainty when uncalibrated, and target resolution that rejects cross-owner IDs. Named/corrected dispositions append source-review-item-keyed samples; correction changes only the current item's association and leaves source samples unchanged; confirmed writes no sample. No global training/model modification.

**Acceptance evidence:** `pytest tests/speaker_review/test_identity_matching.py` passes for ownership, uncertainty, correction lineage, same-recording multiple samples and replay. Matching behavior without calibration remains `uncertain`.

**Validation command:** `pytest tests/speaker_review/test_identity_matching.py` (from `backend/`).

**Dependencies:** T-4, T-10, T-11.

### T-14: GREEN — derive and validate speaker-specific excerpts

**Files:** `backend/app/` excerpt derivation/service modules; `backend/app/infra/` media boundary as needed.

**Action:** Derive candidates solely from target-speaker assigned segments, apply the approved duration/VAD/earliest-start ordering, validate bounds/decoding/speech activity/assignment, and persist an opaque recording- and speaker-bound excerpt reference. Do not expose object-store keys or substitute an excerpt. A missing valid excerpt keeps the revision not-ready and retryable.

**Acceptance evidence:** `pytest tests/speaker_review/test_excerpts.py` passes all candidate ranking, rejection, binding and playback-failure cases.

**Validation command:** `pytest tests/speaker_review/test_excerpts.py` (from `backend/`).

**Dependencies:** T-5.

### T-15: GREEN — gate readiness on durable pipeline stages and recover finalization

**Files:** `backend/app/transcription/`; `backend/app/diarization/`; `backend/app/infra/` queue/outbox and stage persistence modules.

**Action:** Extend the existing async pipeline with lease-based idempotent stage claims, transactional stage output/outbox events and a finalizer that creates review/excerpts only after both stage outputs are complete. Persist readiness atomically; retry finalization from committed outputs without rerunning successful provider stages; do not expose partial reviews.

**Acceptance evidence:** `pytest tests/speaker_review/test_processing_readiness.py` passes for readiness barrier, duplicate deliveries and finalizer recovery.

**Validation command:** `pytest tests/speaker_review/test_processing_readiness.py` (from `backend/`).

**Dependencies:** T-6, T-14.

### T-16: GREEN — enforce resource-owner checks on existing and new routes

**Files:** `backend/app/meetings/router.py`; `backend/app/meetings/service.py`; meeting review/excerpt route modules.

**Action:** Require meeting ID and authenticated principal owner in transcript/diarization legacy handlers and every new review/disposition/excerpt operation. Derive owner only from the authenticated principal, scope all recording/identity/excerpt lookups, and return not-found for absent or non-owned meetings without leaking data.

**Acceptance evidence:** `pytest tests/meetings/test_speaker_review_ownership.py` passes for legacy and new routes, including cross-owner identity/excerpt attempts.

**Validation command:** `pytest tests/meetings/test_speaker_review_ownership.py` (from `backend/`).

**Dependencies:** T-7, T-10, T-13.

### T-17: GREEN — migrate and enforce exact processing revisions

**Files:** `backend/app/infra/models.py`; `backend/app/transcription/`; `backend/app/diarization/`; `backend/app/meetings/`; Alembic migration under `backend/alembic/versions/`.

**Action:** Add per-recording processing state and revision rows, backfill existing stage rows to compatibility revision 1, scope transcript/diarization uniqueness to `(meeting_id, processing_revision_id)`, pin all queue, worker, repository, legacy read, review GET/PUT and excerpt operations to exact revision IDs. Serialize candidate admission and activation with the shared state-row lock. Maintain separate active and in-flight pointers, atomically activate only the current ready candidate, preserve a pending review against distinct reprocessing, and retain the in-flight slot through retryable failures.

**Acceptance evidence:** `pytest tests/speaker_review/test_processing_revisions.py` passes all migration, legacy compatibility, locking, concurrency, retry, pending-review preservation, stale revision and no-mixed-read cases.

**Validation command:** `pytest tests/speaker_review/test_processing_revisions.py` (from `backend/`).

**Dependencies:** T-8, T-14, T-15.

## Phase 3: Web GREEN and Cross-Surface Validation

### T-18: GREEN — add per-speaker review to the transcript view

**Files:** `frontend/src/components/TranscriptView.tsx`; `frontend/src/api.ts`; `frontend/src/components/TranscriptView.test.tsx`.

**Action:** Integrate typed meeting review GET, per-speaker disposition PUT and opaque excerpt playback operations in the existing transcript view. Render uncertain speakers as `Speaker N`, explicit Confirm/Name/Correct controls, pending/complete state and one-item updates; reload server state on remount; keep controls keyboard-operable and show failures without advancing an item locally.

**Acceptance evidence:** `npm run test -- --run src/components/TranscriptView.test.tsx` passes all review tests, including remount and error cases.

**Validation command:** `npm run test -- --run src/components/TranscriptView.test.tsx` (from `frontend/`).

**Dependencies:** T-9.

### T-19: Verify feature package validation and cross-surface contract

**Files:** backend and frontend test/configuration surfaces touched by this plan.

**Action:** Run the approved configured backend and frontend validation commands; add/fix only test wiring needed to validate the implemented API schema/route contract, authenticated owner propagation and review response compatibility. Do not broaden feature scope or alter product requirements.

**Acceptance evidence:** From `backend/`, `pytest`, `ruff check .`, and `mypy .` pass; from `frontend/`, `npm run test`, `npm run typecheck`, and `npm run build` pass. Record complete command output in the implementation PR. If any environment prerequisite prevents a command, document the exact failure as blocked rather than skipping it.

**Validation command:** `pytest && ruff check . && mypy .` (from `backend/`); `npm run test && npm run typecheck && npm run build` (from `frontend/`).

**Dependencies:** T-10, T-11, T-12, T-13, T-14, T-15, T-16, T-17, T-18.

## Dependency DAG and Rationale

- RED suites T-1 through T-9 have no prerequisite edges and can be prepared independently.
- GREEN pairs: T-1 → T-10; T-2 → T-11; T-3 → T-12; T-4 → T-13; T-5 → T-14; T-6 → T-15; T-7 → T-16; T-8 → T-17; T-9 → T-18. These are mandatory RED-before-GREEN edges.
- T-10 → T-11/T-12/T-13/T-16 because those components require the persisted review model/service; T-11 → T-13 because identity sample writes share its transactional idempotency boundary; T-13 → T-16 because route ownership must cover the identity repository; T-14 → T-15/T-17 because readiness/finalization/revision activation cannot complete until validated excerpts are available; T-15 → T-17 because revision processing builds on the stage/finalizer pipeline. T-19 waits for all implementation tasks because it is whole-feature validation.
- No other edges are implied. In particular, unrelated RED suites and their implementation units remain parallel where the listed prerequisites permit.

## Traceability, Assumptions, and Open Implementation Dependencies

- Approved source: `.spectra/specs/recording-speaker-review/requirements.md` (Mira approved; blob `4ed34b66`, approved requirements PR #232); `.spectra/specs/recording-speaker-review/design.md` (Mira approved at commit `014d84c635201d037225b1e0f162264c45e2e2e8`); `PRODUCT_BASELINE.md` approved at commit `f5ff445fd508983740cd6b5a89c08adafcbb9295`, blob `c43cad6515b01a52037ad9cd4e09010a40477fb4` (approval annotation commit `b071a7c6d2c72613aa42543d15e47b81f4999077`).
- Assumptions: existing backend `pytest` and frontend `npm run test` commands are the configured validation entry points; named new test modules are introduced by the RED tasks. The exact embedding model/adapter remains an implementation dependency from the approved design; before calibration, matching must fail closed to uncertain. No threshold or margin value is invented here.
- No product decision is requested. Security review is a required downstream gate for voice-derived identity samples and media access; no security/privacy policy or retention guarantee is decided by this plan.
- Scope excludes capture/control, library, transcript editing, notes, summaries, general media synchronization, visible processing progress/errors, global voice modeling, cross-user sharing, authentication rollout, and retention guarantees.
