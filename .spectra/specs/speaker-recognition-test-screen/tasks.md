# Implementation Plan — Owner-Run Speaker-Recognition Test Screen

## Phase Summary

| Phase | Description | Tasks | Dependencies |
|---|---|---:|---|
| 1 | Frontend upload RED/GREEN | T-1–T-2 | T-1 before T-2 |
| 2 | Test-screen lifecycle RED/GREEN | T-3–T-4 | T-2 and T-3 before T-4 |
| 3 | Speaker-review route and screen RED/GREEN | T-5–T-8 | T-5 before T-6; T-6 and T-7 before T-8 |
| 4 | Linkless upload contract and shared types RED/GREEN | T-9–T-10 | T-9 and T-13 before T-10 |
| 5 | Owner-safe ingestion RED/GREEN | T-11–T-12 | T-10 and T-11 before T-12 |
| 6 | Durable cleanup RED/GREEN | T-13–T-14 | T-13, T-10, and T-12 before T-14 |
| 7 | Meeting status/transcript labels RED/GREEN | T-15–T-16 | T-15 and T-6 before T-16 |
| 8 | Candidate validation and independent gates | T-17 | All implementation tasks |

The graph lists only RED-before-GREEN prerequisites and genuine interface prerequisites. T-12 depends on T-10 because ingestion must not persist null meeting links or accept `web_upload` before the compatible model/schema/type contract exists. T-10 waits for both T-9 and T-13 so the single migration can be tested RED for both the nullable link and cleanup table before it is authored. Tasks that edit separate test seams and production modules otherwise remain dependency-ready; the phase labels do not serialize them.

## Phase 1 — Frontend RED Tests

### T-1: RED — Specify authenticated multipart upload and measured duration

**Tracking:** Issue #552 · Card task_833c47d6ae754443 · PR #570; follow-up bug #574 · Card task_7ca09fe6d0d04cc2 · PR #584 (done)

**Files / test seam:** `frontend/src/api.test.ts` (existing API test module) for `POST /api/v1/ingestion/upload`; upload adapter in `frontend/src/api.ts`; media-metadata/upload behavior in `frontend/src/components/SpeakerRecognitionTestScreen.tsx`.

**Action:** Add failing tests for the existing `audio` and JSON-serialized `data` multipart fields, authorization header, absence of a manually set `Content-Type`, browser-generated multipart boundary, stable `meeting_id` and `idempotency_key` on retry, truthful `web_upload` and `video_presence`, and omission of `meet_link`/`title`. Cover finite browser media duration rounded up with `Math.ceil`, object-URL revocation, and no request when duration is unavailable; do not use a fabricated fallback. Use synthetic media metadata only.

**Acceptance evidence / validation:** Before implementation, `npm run test` from `frontend/` fails on these new assertions for the expected missing behavior. The task is RED only; do not add production implementation.

**Dependencies:** None.

### T-2: GREEN — Implement the authenticated upload adapter and browser duration handling

**Tracking:** Issue #553 · Card task_6dc1779dfd874fed · PR #570

**Files:** `frontend/src/api.ts`, `frontend/src/api.test.ts`, `frontend/src/components/SpeakerRecognitionTestScreen.tsx`.

**Action:** Implement the tested FormData request through the existing API boundary, using authorization without a JSON `Content-Type`; send the selected single audio/video file through `audio`, serialize `IngestionData` into `data`, and derive duration only from finite HTML media metadata. Reuse stable identifiers on retries, revoke the temporary object URL, and decline submission when duration is unavailable. Do not add media limits, title/link fabrication, or error UX beyond existing component behavior.

**REFACTOR:** After T-1's tests pass on the minimum implementation, clean up naming/structure/duplication within the listed files without changing behavior; rerun `npm run test`, `npm run typecheck`, and `npm run build` from `frontend/` and confirm T-1 remains green.

**Acceptance evidence / validation:** `npm run test`, `npm run typecheck`, and `npm run build` from `frontend/` pass; T-1's tests prove the multipart/body and duration contract.

**Dependencies:** T-1.

## Phase 2 — Screen RED Tests and Implementation

### T-3: RED — Specify processing, transcript fidelity, honest labels, and bounded screen scope

**Tracking:** Issue #554 · Card task_6a2457aa02d3464e · PR #668 (done)

**Files / test seam:** `frontend/src/components/SpeakerRecognitionTestScreen.test.tsx`; component behavior in `frontend/src/components/SpeakerRecognitionTestScreen.tsx`; screen selection in `frontend/src/App.tsx`; API read paths in `frontend/src/api.ts`: `GET /api/v1/meetings/{meeting_id}` for persisted processing state, `GET /api/v1/meetings/{meeting_id}/transcript` for completed segments, and `GET /api/v1/meetings/{meeting_id}/speaker-review` for persisted review status/items.

**Action:** Add failing component tests showing that persisted in-progress state is shown before transcript/review data is fetched or rendered; completion loads both in the same flow; each transcript segment displays its timestamp, exact text, and backend speaker label including unresolved `Speaker N`; transcript text is not editable; and the view exposes only upload, progress, transcript inspection, and speaker review rather than a redesigned library or unrelated management controls. Stub API responses only in tests and use synthetic transcript content.

**Acceptance evidence / validation:** Before screen implementation, `npm run test` from `frontend/` fails on the new assertions for the expected missing behavior.

**Dependencies:** None.

### T-4: GREEN — Mount the minimal upload-to-transcript screen

**Tracking:** Issue #555 · Card task_e0ae0aa22694487d · PR #741

**Files:** `frontend/src/App.tsx`, `frontend/src/components/SpeakerRecognitionTestScreen.tsx`, `frontend/src/api.ts`, `frontend/src/components/SpeakerRecognitionTestScreen.test.tsx`.

**Action:** Add the focused screen to the existing SPA. Use the API module for upload and persisted meeting-state observation; only after processing completion load the transcript and review in the same view. Render the backend `segments` wire shape with timestamps, `speaker_label`, and unchanged text. Do not provide transcript editing, library redesign, unrelated meeting controls, invented progress percentages, or new error copy.

**REFACTOR:** After T-3's tests pass on the minimum screen, clean up component naming/structure/duplication within the listed files without changing behavior; rerun `npm run test`, `npm run typecheck`, and `npm run build` from `frontend/` and confirm T-3 remains green.

**Acceptance evidence / validation:** `npm run test`, `npm run typecheck`, and `npm run build` from `frontend/` pass, including T-3's tests.

**Dependencies:** T-2, T-3.

## Phase 3 — Speaker Review RED Tests and Implementation

### T-5: RED — Specify authenticated speaker-review writes and excerpt playback

**Tracking:** Issue #556 · Card task_9fadb56a0a6744a6

**Files / test seam:** `backend/tests/speaker_review/` for authenticated route/authorization/shape tests; route handlers in `backend/app/meetings/router.py` for existing `GET /api/v1/meetings/{meeting_id}/speaker-review`, new `PUT /api/v1/meetings/{meeting_id}/speaker-review/revisions/{revision_id}/speakers/{speaker_id}`, and its `GET /api/v1/meetings/{meeting_id}/speaker-review/revisions/{revision_id}/speakers/{speaker_id}/excerpt` route.

**Action:** Add failing backend tests for the approved route contract: required `Idempotency-Key`, disposition payload and `expected_version`, owner-scoped identity/label changes, excerpt access, and persisted per-speaker disposition without changing another speaker's item or prematurely completing aggregate review. Follow the payload contract already approved by the referenced speaker-review design; do not invent payload fields or behavior beyond the current feature design.

**Acceptance evidence / validation:** Before route implementation, `pytest` from `backend/` fails on the added route/authorization assertions for the expected missing behavior.

**Dependencies:** None.

### T-6: GREEN — Add the authenticated disposition and excerpt handlers

**Tracking:** Issue #557 · Card task_42ba386d7a1a4ea3

**Files:** `backend/app/meetings/router.py`; related `backend/tests/speaker_review/` tests.

**Action:** Implement the two specified authenticated handlers using the approved speaker-review contract and existing per-recording authorization, idempotency, version, and excerpt-access semantics. Persist only the targeted speaker disposition; preserve pending aggregate state until every displayed speaker has an explicit persisted disposition. Do not add a parallel review model or endpoint family.

**REFACTOR:** After T-5's tests pass on the minimum route implementation, clean up handler structure/naming/duplication within the listed files without changing behavior; rerun `pytest`, `ruff check .`, and `mypy .` from `backend/` and confirm T-5 remains green.

**Acceptance evidence / validation:** `pytest`, `ruff check .`, and `mypy .` from `backend/` pass; T-5's tests pass.

**Dependencies:** T-5.

### T-7: RED — Specify persisted review isolation and resume behavior in the screen

**Tracking:** Issue #558 · Card task_106080f9d51c4fe4

**Files / test seam:** `frontend/src/components/SpeakerRecognitionTestScreen.test.tsx`; `frontend/src/api.ts` operations `GET /api/v1/meetings/{meeting_id}/speaker-review`, `PUT /api/v1/meetings/{meeting_id}/speaker-review/revisions/{revision_id}/speakers/{speaker_id}`, and `GET /api/v1/meetings/{meeting_id}/speaker-review/revisions/{revision_id}/speakers/{speaker_id}/excerpt`; `SpeakerRecognitionTestScreen` review interaction.

**Action:** Add failing tests proving that naming/correcting one speaker changes only that item, an incomplete review stays pending, and unmounting/reopening the same recording reloads persisted pending items rather than locally marking review complete. Include excerpt playback and both naming an unresolved `Speaker N` and correcting an assigned name. Use synthetic API data.

**Acceptance evidence / validation:** Before UI implementation, `npm run test` from `frontend/` fails on the new assertions for the expected missing behavior.

**Dependencies:** None.

### T-8: GREEN — Implement speaker-review persistence and resume in the test screen

**Tracking:** Issue #559 · Card task_01b0ed28162d4326

**Files:** `frontend/src/api.ts`, `frontend/src/components/SpeakerRecognitionTestScreen.tsx`, `frontend/src/components/SpeakerRecognitionTestScreen.test.tsx`.

**Action:** Add API wrappers and snake_case response DTO normalization for the approved read/write/excerpt operations. Implement per-speaker review actions and reload server-persisted state when a recording is reopened. Keep completion derived from persisted aggregate status and keep transcript text read-only.

**REFACTOR:** After T-7's tests pass on the minimum review flow, clean up adapter/component naming/structure/duplication within the listed files without changing behavior; rerun `npm run test`, `npm run typecheck`, and `npm run build` from `frontend/` and confirm T-7 remains green.

**Acceptance evidence / validation:** `npm run test`, `npm run typecheck`, and `npm run build` from `frontend/` pass, including T-7's tests.

**Dependencies:** T-6, T-7.

## Phase 4 — Linkless Upload Contract RED Tests and Implementation

### T-9: RED — Specify linkless meetings and web-upload type/schema compatibility

**Tracking:** Issue #560 · Card task_59e29b213486474d

**Files / test seam:** `backend/tests/meetings/` for nullable meeting-link serialization; `backend/tests/` migration coverage for the nullable-link migration; `packages/shared-types/` typecheck seam for `Meeting.meetLink` and `CaptureOrigin`.

**Action:** Add failing backend assertions for upload-created meetings having no Meet link and migration/schema support for nullable `meetings.meet_link`; verify the shared contract accepts `meetLink: string | null` and `CaptureOrigin.WebUpload`. Do not add a new endpoint or fabricate a Meet URL.

**Acceptance evidence / validation:** Before implementation, `pytest` from `backend/` and `npm run typecheck` from `packages/shared-types/` fail on the new assertions/type usage for the expected missing contract.

**Dependencies:** None.

### T-10: GREEN — Add nullable meeting links and the web-upload contract

**Tracking:** Issue #561 · Card task_094a330d32cd462b · PR #590

**Files:** `backend/app/infra/models.py`, the existing ingestion schema in `backend/app/ingestion/`, the single sequential Alembic migration after `010_speaker_excerpt_reference`, `packages/shared-types/src/index.ts`, and corresponding backend tests.

**Action:** Make `Meeting.meet_link` nullable, add `web_upload` to the accepted capture-origin contract, and add the `PendingObjectDeletion` model specified in the design. Update shared TypeScript types. Create one sequential migration that both makes `meetings.meet_link` nullable and creates the pending-deletion table; its downgrade must refuse while null links or pending rows exist. Preserve existing fields and do not change Compose configuration.

**REFACTOR:** After T-9 and T-13's RED assertions fail as expected and pass on the implementation, clean up model/schema/migration/type structure within the listed files without behavior change; rerun `pytest`, `ruff check .`, `mypy .` from `backend/`, plus `npm run typecheck` from `packages/shared-types/` and `extension/`.

**Acceptance evidence / validation:** `pytest`, `ruff check .`, and `mypy .` from `backend/`; `npm run typecheck` from `packages/shared-types/`; and `npm run typecheck` from `extension/` all pass. T-9's assertions pass; T-13's model/migration assertions pass when run after its RED test task.

**Dependencies:** T-9, T-13.

## Phase 5 — Owner-Safe Ingestion RED Tests and Implementation

### T-11: RED — Specify owner-safe upload idempotency and collision handling

**Tracking:** Issue #562 · Card task_c989fff93daf41bf

**Files / test seam:** `backend/tests/ingestion/test_idempotency_property.py` and `backend/tests/ingestion/test_playback_source_ingestion.py`; ingestion preflight and `process_ingestion` in `backend/app/ingestion/router.py` and `service.py`.

**Action:** Add failing tests for owner-scoped meeting checks before object writes, exact same-owner/same-meeting retry, non-disclosing not-found for foreign meeting/key, generic conflict for same-owner key reuse across meetings, and reclassification of a concurrent unique-key race after rollback and a fresh lookup. Assert no foreign recording ID/state or media refs are exposed/deleted.

**Acceptance evidence / validation:** Before implementation, `pytest` from `backend/` fails on the added ownership/idempotency cases for the expected missing behavior.

**Dependencies:** T-10.

### T-12: GREEN — Implement owner-safe ingestion retries and linkless creation

**Tracking:** Issue #563 · Card task_7bde75fa77f34e37 · PR #601 (done)

**Files:** `backend/app/ingestion/router.py`, `backend/app/ingestion/service.py`, existing ingestion schema and `backend/tests/ingestion/`.

**Action:** Verify an existing meeting belongs to the authenticated user and classify idempotency keys through their meeting owner before storing media; repeat checks inside `process_ingestion` to cover races. Return prior ID/state only for an exact same-owner/same-meeting retry, non-disclosing not-found for foreign resources and generic conflict for same-owner cross-meeting key reuse. Create upload-only meetings without a fabricated Meet link and enqueue processing through the existing path. Leave draining pending deletion tasks before duplicate success to T-14.

**REFACTOR:** After T-11's tests pass on the minimum ingestion implementation, clean up the owner-check/idempotency code structure within the listed files without changing behavior; rerun `pytest`, `ruff check .`, and `mypy .` from `backend/` and confirm T-11 remains green.

**Acceptance evidence / validation:** `pytest`, `ruff check .`, and `mypy .` from `backend/` pass, including T-11's tests.

**Dependencies:** T-10, T-11.

## Phase 6 — Durable Cleanup RED Tests and Implementation

### T-13: RED — Specify durable staged-media cleanup and recovery

**Tracking:** Issue #564 · Card task_3f82fcec75ca4fc8

**Files / test seam:** `backend/tests/retention/test_pending_object_cleanup.py` for `drain_pending_object_deletions(session, object_store, cleanup_scope_hash=None)` in `backend/app/retention/cleanup.py` and scheduled `start_retention_worker` in `backend/app/retention/worker.py`; `backend/tests/infra/test_adaptadores_conformidad_property.py` for `ObjectStore.delete` idempotency; migration coverage in `backend/tests/`.

**Action:** Add failing tests for the pending-deletion table/model contract (unique scope/ref, no meeting/recording foreign key, and downgrade protection for outstanding tasks), per-ref durable tasks before deletion, idempotent repeated delete, partial failure retaining only failed refs, live-reference protection, exact-scope retry draining before duplicate success, scheduled recovery, and never queuing committed recording refs (including post-commit queue failure). Use synthetic refs and fake external I/O only in tests.

**Acceptance evidence / validation:** Before cleanup implementation, `pytest` from `backend/` fails on the new cleanup assertions for the expected missing behavior.

**Dependencies:** None.

### T-14: GREEN — Implement durable pending-object cleanup

**Tracking:** Issue #565 · Card task_525bee7872064383 · PR #728 (open; implementation done)

**Files:** `backend/app/retention/cleanup.py`, `backend/app/retention/worker.py`, `backend/app/infra/object_store.py`, ingestion cleanup integration, and corresponding backend tests.

**Action:** Use the `PendingObjectDeletion` model and table from T-10. Persist each uncommitted attempt's unique refs in a separate committed transaction before deletion; delete only unreferenced refs; remove each task only after successful idempotent deletion; preserve failures for exact-scope retry and the existing scheduled retention worker. Do not store raw idempotency keys, delete live refs, or queue committed recording media. Use only the existing worker; no Compose service.

**REFACTOR:** After T-13's tests pass on the minimum cleanup implementation, clean up deletion/worker structure within the listed files without changing behavior; rerun `pytest`, `ruff check .`, and `mypy .` from `backend/` and confirm T-13 remains green.

**Acceptance evidence / validation:** `pytest`, `ruff check .`, and `mypy .` from `backend/` pass, including T-13's tests.

**Dependencies:** T-10, T-12, T-13.

## Phase 7 — Meeting State and Transcript RED Tests and Implementation

### T-15: RED — Specify owner-protected polling and revision-correct speaker labels

**Tracking:** Issue #566 · Card task_15b2006993284783

**Files / test seam:** `backend/tests/meetings/`; `GET /api/v1/meetings/{meeting_id}` and `GET /api/v1/meetings/{meeting_id}/transcript` handlers in `backend/app/meetings/router.py`.

**Action:** Add failing tests for foreign-owner denial before polling, transcript loading only from one active processing revision, exact `SpeechTurn.id` → `SpeakerAssignment.turn_id` → `Speaker.id` joins, same-revision `speaker_key == str(Speaker.id)`, named/corrected `chosen_label`, unresolved `Speaker N` fallback, multiple-speaker isolation, and unchanged transcript text.

**Acceptance evidence / validation:** Before router implementation, `pytest` from `backend/` fails on the added ownership and effective-label assertions for the expected missing behavior.

**Dependencies:** None.

### T-16: GREEN — Protect meeting polling and return effective transcript labels

**Tracking:** Issue #567 · Card task_b30e036fa70d4984

**Files:** `backend/app/meetings/router.py`, related meetings transcript/authorization code, and `backend/tests/meetings/`.

**Action:** Enforce meeting ownership on the existing persisted-state GET before polling. Extend the existing transcript response with `speaker_label` using only the active revision and the approved turn-assignment-speaker/review key joins; return persisted `chosen_label` for named/corrected dispositions, otherwise the review current label, and retain the diarization label only when no review item exists. Do not alter transcript text or infer identity.

**REFACTOR:** After T-15's tests pass on the minimum router implementation, clean up meeting authorization/label-join structure within the listed files without changing behavior; rerun `pytest`, `ruff check .`, and `mypy .` from `backend/` and confirm T-15 remains green.

**Acceptance evidence / validation:** `pytest`, `ruff check .`, and `mypy .` from `backend/` pass, including T-15's tests.

**Dependencies:** T-15, T-6.

## Phase 8 — Cross-Surface Validation

### T-17: Run configured validation on the integrated candidate

**Tracking:** Issue #568 · Card task_73360b13a3c14544

**Files / evidence:** Exact candidate commit; test/build/typecheck outputs for every changed surface.

**Action:** After all implementation tasks are complete, run the configured commands for every changed surface: from `frontend/`, `npm run test`, `npm run typecheck`, `npm run build`; from `backend/`, `pytest`, `ruff check .`, `mypy .`; from `packages/shared-types/`, `npm run typecheck`; and from `extension/`, `npm run typecheck`. Record exact outputs and candidate SHA. Use synthetic recording/transcript data only. Do not claim local Compose diarization runtime is available: the design records its deployment/configuration prerequisites separately.

**Acceptance evidence / validation:** All listed configured commands pass on the same candidate SHA; retain the command outputs as evidence.

**Dependencies:** T-2, T-4, T-6, T-8, T-10, T-12, T-14, T-16.

## Independent Release Gates (not implementation tasks)

- **QA:** Nia reports `PASS` on the exact candidate SHA after validating the user flow; QA remains independent from implementation.
- **Security:** Zev reviews the exact candidate for authenticated upload/identity boundaries and staged-media cleanup, reporting `NO_ACTIONABLE_FINDINGS` or findings for remediation.
- **Product acceptance:** Cyrus records `PRODUCT_ACCEPTED` for this user-visible feature against the exact tested candidate version, using predeclared user-test criteria. A passing technical test suite is not product acceptance.

## Dependency Graph and Rationale

- `T-1 → T-2`; `T-2 + T-3 → T-4`: required RED-before-GREEN, and the mounted screen uses the implemented API adapter.
- `T-5 → T-6`; `T-6 + T-7 → T-8`: backend review operations must exist before the screen's write/playback adapter can complete its flow; the UI tests must fail before UI implementation.
- `T-9 + T-13 → T-10`: the single migration/model contract must be tested RED for both nullable links and the cleanup table before implementation; it also establishes the shared `web_upload` type/schema contract needed by ingestion.
- `T-11 → T-12`: mandatory test-before-code for owner-safe idempotency; T-12 also follows T-10 because upload depends on the compatible nullable-link and `web_upload` contract.
- `T-13 + T-10 + T-12 → T-14`: mandatory RED-before-GREEN for durable cleanup; the single migration/model is created in T-10, and cleanup integration uses the owner-safe ingestion path from T-12.
- `T-15 → T-16`; T-6 precedes T-16 because transcript labels read the approved persisted review contract.
- T-17 follows all feature implementations because it validates the integrated candidate; Nia, Zev, and Cyrus then provide independent gates on that exact candidate, not additional implementation dependencies.
- No other edges are imposed; independent test/implementation lanes may run in separate worktrees when their explicit prerequisites are met.

## Assumptions and Prerequisites

- Requirements and design are the approved behavior and implementation sources; exact upstream references are included in the handoff. Baseline commit `f5ff445fd508983740cd6b5a89c08adafcbb9295` is reference context only; PR #528 at `f31c1437d002a49849fc577446290ab83d29a584` is unmerged and is not treated as a different authority.
- Use the existing authenticated ingestion, meeting, transcript, speaker-review, and retention flows; exact route and DTO behavior follows the approved design and its already-approved speaker-review contract. Do not invent media limits, progress percentages, error copy, endpoint families, or fallback duration values.
- The configured frontend, backend, shared-types, and extension commands listed above are the validation commands named by the approved design and repository structure. No tests were run while authoring this plan.
- Run implementation tests against synthetic media/transcript fixtures only. Fresh-database / real end-to-end checks, secure `HF_TOKEN` provisioning, diarization runtime setup, and ASR model-size evaluation remain separate prerequisites and are not silently declared satisfied by these tasks.
