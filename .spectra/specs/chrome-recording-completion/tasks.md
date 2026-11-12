# Implementation Plan — Chrome Recording Completion

## Upstream traceability

- Approved baseline snapshot: `PRODUCT_BASELINE.md` commit `4953b3b4b8a058fd4738342307cc50bfd66814f1`, blob `c6f9ef9bf3fac9eac23763e25e25e1089a16c446` (context only; it does not authorize this extension delta).
- Requirements: `.spectra/specs/chrome-recording-completion/requirements.md`, Mira APPROVED, snapshot `98e52824d5b8f30f5e1b189c3d4f2ce5aed926f2`, PR #605 (not merged at planning time).
- Design: `.spectra/specs/chrome-recording-completion/design.md`, Mira APPROVED, corrected snapshot `a477c0bde2ac3f140d04020af06afa05fb96c4f6`, PR #608.
- Owner direction: 2026-10-30; requirements contain traceability to the source direction and Cyrus reconciliation.
- Import provenance: requirements and `.config.spectra` remain byte-identical to the approved source worktree; the design matches exact approved snapshot `a477c0bde2ac3f140d04020af06afa05fb96c4f6` (Git blob `ec67cad96b6907911f2f335b17917753993d6937`, SHA-256 `16bbfc35dcaf3a4ccc74b8e21790ca12faf2be30d51591c03f6bde465383ba6a`).

## Summary of phases

| Phase | Description | Tasks | Dependencies |
|---|---|---|---|
| 1 | RED tests for lifecycle, durable-state migration, provider adapters, and protected review invariants | T1.1–T1.9 | T1.8 follows T1.1/T1.2; T1.6 follows named API/playback prerequisites; other RED tests independent |
| 2 | GREEN lifecycle, IndexedDB v2, provider adapters, status presentation, and review flow | T2.1–T2.8 | Matching RED; true upload/API/login/playback prerequisites; shared `background.ts` edits serialize T2.1→T2.7→T2.3→T2.4→T2.5 |
| 3 | End-to-end integration and changed-contract security verification | T3.1–T3.2 | Extension GREEN tasks; upstream portal/API and playback tasks |

**Validation environment:** extension tests/build/typecheck use the existing scripts in `extension/package.json`: `cd extension && npm run test -- <test-file>`, `npm run typecheck`, `npm run build`, and `npm run test:e2e`. Property tests use the already-declared `fast-check` dependency and must run at ≥100 generated cases per property. If npm dependencies/test runner are not available in a fresh worktree, resolve that environment prerequisite before implementation; do not skip RED execution. Use synthetic recordings, IDs, and server responses only. Frontend and backend commands apply only if those surfaces/contracts are actually changed: `cd frontend && npm run test/typecheck/build`; `cd backend && pytest` (or the configured narrow pytest path).

## Phase 1: Required RED tests

### Tarea 1.1: Test Stop and captured-tab-close completion behavior at existing listeners

**Archivo:** `extension/src/background.recording-completion.test.ts`; existing `chrome.tabs.onRemoved`, `meet-ended`, and `stop-capture` listeners in `extension/src/background.ts`, using the listener-invocation harness from `extension/src/background.tab-close.test.ts`
**Acción:** Before changing production code, extend the existing Chrome/storage test harness to exercise the real background listeners with synthetic session and tab IDs. Use `fast-check` to generate ≥100 cases per property for Stop, captured-tab-close, both event orders, duplicate triggers, and meeting-ended-only input. Assert observable listener effects/state: Stop and captured-tab-close complete the same active recording at most once; meeting-ended alone neither finalizes nor clears/detaches the active recording, and a later captured-tab-close still reaches its completion effect. The test must produce an executed behavioral assertion counterexample against current listeners; an import/setup failure, zero collected cases, or an inferred-but-unrun failure does not satisfy RED. Make no production changes in this task.
**Criterio de Completado:** `cd extension && npm run test -- src/background.recording-completion.test.ts` executes every property with ≥100 generated cases and fails on a behavioral assertion demonstrating the current listener defect; the test uses synthetic IDs and reuses the tab-close listener harness.
**Dependencias:** Ninguna.

### Tarea 1.2: Test durable identity conservation and atomic completion claims

**Archivo:** `extension/src/recording-db.test.ts`; persistence seam `openDB()` and IndexedDB upgrade/transaction boundaries in `extension/src/recording-db.ts`
**Acción:** With a populated synthetic v1 `sauri-recordings` fixture, call `openDB()` to exercise the v1→v2 upgrade. Assert the existing `chunks` store, key path, `by_session` index, and chunk rows remain readable; the new `completion_records` store is keyed by `sessionId` and has a non-unique `capturedTabId` index; no completion rows are synthesized for legacy chunks. Use `fast-check` to generate ≥100 synthetic `provider`/ID/retry sequences and assert durable `sessionId → meetingId → recordingId` identity conservation, retry/reload preservation, mismatch rejection, and transactional duplicate finalization/launch claims. Include `blocked`/`versionchange` handling without data loss.
**Criterio de Completado:** `cd extension && npm run test -- src/recording-db.test.ts` fails against v1 behavior and verifies the v1→v2 migration, preserved chunk data/indexes, new completion store/index, and ≥100 generated identity/claim cases.
**Dependencias:** Ninguna.

### Tarea 1.3: Test truthful upload outcome mapping

**Archivo:** `extension/src/upload-queue.property.test.ts`; seams `uploadRecording` / `processUploadQueue` in `extension/src/upload-queue.ts`
**Acción:** At the existing result seams, use `fast-check` to generate ≥100 synthetic success, network, non-2xx, invalid-response, and retry cases. Assert only a valid successful response for the same mapping reports success; all unsettled/failed results remain failure/unavailable, and retries retain the exact `sessionId` and `meetingId`.
**Criterio de Completado:** `cd extension && npm run test -- src/upload-queue.property.test.ts` fails for the missing truthful queue contract and includes ≥100 generated response/retry cases.
**Dependencias:** Ninguna.

### Tarea 1.4: Test owner-authorized status and same-meeting processing success

**Archivo:** `extension/src/background.processing-status.test.ts`; seam `completeRecording(sessionId, trigger)` in `extension/src/background.ts`; backend seam `get_meeting_endpoint` for `GET /api/v1/meetings/{meeting_id}` in `backend/app/meetings/router.py`, tested by `backend/tests/meetings/test_get_meeting_property.py`
**Acción:** At `completeRecording(sessionId, trigger)`, use `fast-check` to generate ≥100 synthetic combinations of documented `process_state`, transcript/video availability, and meeting/recording identity. Assert `processing_succeeded` occurs only for completed status plus both same-meeting assets and matching mapping; pending, failed, unavailable, or mismatched cases never succeed. At the existing `get_meeting_endpoint`, verify `_get_authorized_meeting` enforces ownership: the owner receives status, unauthenticated access returns 401, and a different authenticated user requesting an existing synthetic meeting receives 404 with no status/recording fields. Use synthetic DB fixtures and users.
**Criterio de Completado:** `cd extension && npm run test -- src/background.processing-status.test.ts` fails on the missing completion gate and covers ≥100 generated state/asset/mapping combinations; `cd backend && pytest tests/meetings/test_get_meeting_property.py` fails on missing owner authorization and asserts owner success, unauthenticated 401, and non-owner 404/no status disclosure.
**Dependencias:** Ninguna.

### Tarea 1.5: Test review launch gating and at-most-one recovery

**Archivo:** `extension/src/background.review-launch.test.ts`; service-worker review-launch path in `extension/src/background.ts`, including the design-specified `chrome.tabs.create` boundary
**Acción:** Use `fast-check` to generate ≥100 synthetic duplicate/retry/restart event sequences against the persisted review-launch claim/reconciliation path. Assert at most one claim/tab creation and only after `processing_succeeded`; cover a pending marker and discovery of an existing matching canonical Sauri target at the `chrome.tabs.create` boundary.
**Criterio de Completado:** `cd extension && npm run test -- src/background.review-launch.test.ts` fails on duplicate launch or launch before verified success and includes ≥100 generated launch sequences plus matching-target recovery.
**Dependencias:** Ninguna.

### Tarea 1.6: Test authorization boundary for transcript and playback endpoints

**Archivo:** `backend/tests/meetings/test_review_asset_authorization.py`; seams `backend/app/meetings/router.py:get_transcript`, `get_playback_manifest`, `_get_authorized_meeting`
**Acción:** Write RED endpoint tests for `GET /api/v1/meetings/{meeting_id}/transcript` and `GET /api/v1/meetings/{meeting_id}/playback`. Verify unauthenticated and non-owner users receive no transcript/video asset, and an authorized owner receives only assets for the requested synthetic meeting. Keep review rendering/playback behavior owned by `task_6a271652b2c34130`.
**Criterio de Completado:** `cd backend && pytest tests/meetings/test_review_asset_authorization.py` fails if either named handler returns protected assets without `get_current_user` authentication and `_get_authorized_meeting` authorization; fixtures use synthetic IDs and media.
**Dependencias:** `task_dfcb314806c04033` (portal API/login contract), `task_6a271652b2c34130` (protected review destination and endpoint contract).

### Tarea 1.7: Test provider-neutral Meet and Teams completion adapters

**Archivo:** `extension/src/background.tab-close.test.ts`; seams `completeRecording(sessionId, trigger)`, provider-neutral `{ provider, capturedTabId, sessionId }` handles, `chrome.runtime.onMessage`, and captured-tab lifecycle in `extension/src/background.ts`
**Acción:** Using synthetic Meet and Teams capture handles, verify each adapter supplies the same provider-neutral handle to `completeRecording`, and Stop/tab-close use the same persisted session binding. Assert a meeting-ended message from either provider does not finalize, stop capture, or clear/detach the active completion record; a later tab-close still resolves the associated session after worker restart. If an adapter cannot resolve its active handle, assert no unrelated session is finalized and the completion remains non-successful with an error available for Side Panel presentation. Do not add or claim a Teams media-capture pipeline or unrelated controls.
**Criterio de Completado:** `cd extension && npm run test -- src/background.tab-close.test.ts` fails for either adapter path if provider/session/tab association is lost, meeting-ended triggers completion, tab-close cannot resume the right active session, or an unresolved handle finalizes a different session; fixtures use synthetic provider handles and IDs.
**Dependencias:** Ninguna.

### Tarea 1.8: Test automatic enqueue of finalized audio and video

**Archivo:** `extension/src/background.test.ts`; seam `completeRecording(sessionId, trigger)` → existing upload-queue enqueue boundary
**Acción:** Add a required RED integration test that completes a synthetic recording and asserts the finalized audio and video are automatically enqueued once with the existing `sessionId` and persisted `meetingId`; assert no separate user upload action is required and duplicate trigger does not enqueue a second recording.
**Criterio de Completado:** `cd extension && npm run test -- src/background.test.ts` fails before implementation because completion does not yet enqueue the finalized media automatically; assertion verifies both media references and stable IDs.
**Dependencias:** T1.1, T1.2.

### Tarea 1.9: Test truthful Side Panel status and recovery for the same recording

**Archivo:** `extension/src/panel/SidePanelApp.test.tsx` and `extension/src/panel/components/RecordingCompletionStatus.test.tsx`; component/subscription seams `SidePanelApp` and `RecordingCompletionStatus`
**Acción:** Add RED component/integration coverage for the design-defined durable status subscription keyed by `sessionId`, loading persisted records after Side Panel reopen or service-worker restart, and rendering exactly one current outcome: finalizing (including unresolved-adapter error), upload in progress/succeeded/failed/unavailable, processing in progress/failed/status unavailable, and review ready/opened. Assert ready/opened requires the same-recording transcript and playable-video checks, and no stale status from another session appears. Use synthetic IDs and statuses only.
**Criterio de Completado:** `cd extension && npm run test -- src/panel/SidePanelApp.test.tsx src/panel/components/RecordingCompletionStatus.test.tsx` fails before implementation and asserts accessible visible outcomes, same-session recovery, unresolved-handle feedback, and no cross-recording stale success.
**Dependencias:** Ninguna.

## Phase 2: GREEN implementation

### Tarea 2.1: Implement one idempotent completion transition for authorized triggers

**Archivo:** `extension/src/content.ts`, `extension/src/background.ts`, and new pure transition logic/tests in `extension/src/core/recording-completion.ts` and `extension/src/core/recording-completion.test.ts`
**Acción:** After T1.1 has recorded its executed behavioral counterexample, implement a pure completion transition/idempotency seam and route explicit Stop and closure of the specifically associated captured tab through `completeRecording(sessionId, trigger)`. Preserve the captured-tab/session binding, make duplicate triggers converge on one completion, and ensure meeting-ended alone neither finalizes nor clears/detaches the active completion record. Add follow-up `fast-check` properties against the new pure seam (≥100 cases per property, synthetic IDs) for both authorized triggers, both event orders, duplicates, and meeting-ended-only input; retain T1.1's listener-level regression tests. Leave media finalization in the existing capture/offscreen owner.
**Criterio de Completado:** T1.1's listener-level regression test and the new pure-seam properties pass with ≥100 generated cases per property; `cd extension && npm run test -- src/background.recording-completion.test.ts src/core/recording-completion.test.ts`, `cd extension && npm run typecheck`, and `cd extension && npm run build` pass.
**Dependencias:** T1.1.

### Tarea 2.2: Migrate IndexedDB v1→v2 and persist completion identity/state

**Archivo:** `extension/src/recording-db.ts` and `extension/src/recording-db.test.ts`
**Acción:** Upgrade `sauri-recordings` from DB_VERSION 1 to 2 additively. Preserve `chunks`, its key path, `by_session` index, and every existing chunk row; add `completion_records` keyed by `sessionId` with a non-unique `capturedTabId` index; do not synthesize completion rows from legacy chunks. Handle `onblocked`/`versionchange` by closing live connections. Persist `{ provider, capturedTabId, sessionId }`, one `meetingId`, returned `recordingId`, lifecycle status, and atomic finalization/review claims in transactions. On upgrade/write failure retain capture data and never report success; persist no tokens, transcript/audio, or unbounded error payloads.
**Criterio de Completado:** T1.2 passes, including populated-v1 upgrade/data/index preservation and duplicate-claim cases; `cd extension && npm run test -- src/recording-db.test.ts`, `cd extension && npm run typecheck`, and `cd extension && npm run build` pass.
**Dependencias:** T1.2.

### Tarea 2.3: Consume truthful upload queue results without duplicating upload repair

**Archivo:** `extension/src/upload-queue.ts`, `extension/src/background.ts`
**Acción:** After `completeRecording(sessionId, trigger)` successfully finalizes both assets, enqueue those finalized media references exactly once through the existing upload queue with persisted `sessionId` and `meetingId`; persist returned `recordingId`, reflect success only from a valid success result, and integrate (not implement) the separately owned upload-failure contract.
**Criterio de Completado:** T1.3 and T1.8 pass; both media assets are automatically enqueued without user action, retries retain the same identity, and failure/unavailable queue results never appear as success.
**Dependencias:** T1.3, T1.8, T2.1, T2.2, T2.7 (serializes the verified shared `extension/src/background.ts` edit), `task_11001b7f5b084e09` (separate upload failure/result-contract repair).

### Tarea 2.4: Enforce owner authorization for status and gate processing success on both protected assets

**Archivo:** `backend/app/meetings/router.py:get_meeting_endpoint`, `extension/src/background.ts`, and the status mapping/bridge under `extension/src/core/`
**Acción:** On the existing `GET /api/v1/meetings/{meeting_id}` handler, enforce meeting ownership for the authenticated user using the existing meetings authorization boundary; return 404 for a non-owner without disclosing meeting status or recording fields, while preserving 401 for unauthenticated requests. Do not add a parallel route. In the extension status bridge, map documented `process_state` values; for `completed`, require the persisted `meetingId`, matching `recordingId`, protected transcript availability, and usable playback-manifest video before persisting `processing_succeeded`. Preserve unavailable/auth-required, failed, and non-ready states without inventing retry intervals or limits. Publish per-recording status for T2.8; do not implement a speculative UI component.
**Criterio de Completado:** T1.4 passes with owner success, unauthenticated 401, and non-owner 404/no status disclosure; `cd backend && pytest tests/meetings/test_get_meeting_property.py` and `cd extension && npm run test -- src/background.processing-status.test.ts` pass; `cd extension && npm run typecheck` passes. The status bridge emits the matching durable per-recording state consumed by T2.8.
**Dependencias:** T1.4, T2.2, T2.3 (provides the persisted `recordingId` bound to the meeting), `task_6a271652b2c34130` (protected transcript/playback asset contract).

### Tarea 2.5: Open one authenticated review destination only after verified success

**Archivo:** `extension/src/background.ts`; consume the protected review route in `frontend/src/` without changing playback behavior
**Acción:** Claim and persist the launch marker before `chrome.tabs.create`; resolve destination by persisted `meetingId`, verify mapping, store tab result and reconcile pending launches by finding an existing matching canonical Sauri target before creating another. The extension carries no protected transcript/video data.
**Criterio de Completado:** T1.5 passes; `cd extension && npm run typecheck` passes; opening is impossible from pending, failure, or unavailable state and repeated/recovered launch produces no second tab.
**Dependencias:** T1.5, T2.2, T2.4, `task_6a271652b2c34130`.

### Tarea 2.6: Preserve the authorization boundary in any changed review contract

**Archivo:** Actual protected route/API files in `frontend/src/` and, only if required, `backend/app/meetings/` or current ingestion/recording owner
**Acción:** Integrate the launch target with existing authenticated/authorized review behavior. Change a backend or frontend contract only if the approved task's inspection shows it is missing; keep API calls in `frontend/src/api.ts` and do not implement playback media behavior assigned to the playback task.
**Criterio de Completado:** T1.6 passes; for each changed surface run its configured tests, typecheck and build (`frontend`: `npm run test`, `npm run typecheck`, `npm run build`; backend: `pytest <matching test path>`, plus existing configured checks). No protected asset is returned before authorization.
**Dependencias:** T1.6, `task_dfcb314806c04033`, `task_6a271652b2c34130`.

### Tarea 2.7: Wire provider-neutral Meet and Teams completion adapters

**Archivo:** `extension/src/content.ts`, `extension/src/background.ts`, and the provider-neutral completion contract under `extension/src/core/`
**Acción:** Wire the existing Meet adapter and a Teams completion adapter to supply `{ provider, capturedTabId, sessionId }` plus the already-available finalized media handle to the shared `completeRecording(sessionId, trigger)` coordinator. Keep capture finalization in its existing owner; the Teams adapter accepts a provided capture handle but does not create or claim a Teams media-capture pipeline or add unrelated controls. If the active handle cannot be resolved, leave the record non-successful, do not finalize another session, and expose the completion error through the Side Panel status path. A `meeting-ended` signal from either provider must not clear the active durable binding or trigger finalization; no visual redesign, consent, or retention changes.
**Criterio de Completado:** T1.7 passes for both synthetic provider handles and unresolved-handle safety; `cd extension && npm run typecheck` passes, and implementation does not introduce or claim an independent Teams capture pipeline.
**Dependencias:** T1.7, T2.1, T2.2.

### Tarea 2.8: Present and recover truthful recording outcomes in the Side Panel

**Archivo:** `extension/src/panel/SidePanelApp.tsx`, new `extension/src/panel/components/RecordingCompletionStatus.tsx`, and `extension/src/panel/components/RecordingCompletionStatus.test.tsx`
**Acción:** Subscribe to durable completion-record updates by `sessionId` and load the persisted record when the Side Panel opens. Render the recording identity and exactly one current outcome (finalizing/unresolved-adapter error, upload in progress/succeeded/failed/unavailable, processing in progress/failed/status unavailable, review ready/opened); never infer success from idle worker state or queue dispatch. Review ready/opened requires confirmed assets for the same recording. Recover after panel close/reopen and worker restart without showing another session's stale status. Offer retry/status refresh only where an existing API supports it; do not implement upload repair or redesign the panel.
**Criterio de Completado:** T1.9 passes for all visible outcomes, exact-session recovery, unresolved-handle feedback, and no cross-recording stale success; `cd extension && npm run typecheck` and `cd extension && npm run test -- src/panel/SidePanelApp.test.tsx src/panel/components/RecordingCompletionStatus.test.tsx` pass.
**Dependencias:** T1.9, T2.2, T2.3, T2.4, T2.7.

## Phase 3: Integration and validation

### Tarea 3.1: Verify synthetic completion-to-review end-to-end flow

**Archivo:** `extension/tests/e2e/`
**Acción:** Add E2E coverage of synthetic Meet and Teams adapter handles through completion, upload/status reconciliation, Side Panel recovery, and one authenticated Sauri review target. Include meeting-ended then captured-tab-close, worker/panel restart, duplicate completion, and processing unavailable/failure cases. Mock external network only at test boundaries; use synthetic handles and no live capture or real meeting data.
**Criterio de Completado:** `cd extension && npm run test:e2e` passes for both provider adapter paths, with a single matching target opened only after confirmed processing success; pending/failed/unavailable cases do not open a ready review tab and no Teams capture pipeline is implied.
**Dependencias:** T2.1–T2.8, `task_11001b7f5b084e09`, `task_dfcb314806c04033`, `task_6a271652b2c34130`.

### Tarea 3.2: Run configured validation for the changed product surfaces

**Archivo:** Changed extension/frontend/backend surface test suites
**Acción:** Run the design's configured commands only for surfaces actually changed: extension test/typecheck/build/E2E; frontend test/typecheck/build if changed; backend pytest if changed. Record exact successful outputs and fix regressions before implementation PR.
**Criterio de Completado:** Every applicable configured validation command exits successfully on the implementation candidate; unmodified surfaces are not run as an invented gate.
**Dependencias:** T3.1.

## Dependency graph and rationale

- Mandatory RED→GREEN edges: T1.1→T2.1; T1.2→T2.2; T1.3+T1.8→T2.3; T1.4→T2.4; T1.5→T2.5; T1.6→T2.6; T1.7→T2.7; T1.9→T2.8. T1.8 also depends on T1.1/T1.2 because it exercises the completion coordinator and persisted identity before enqueue.
- Actual implementation prerequisites: T2.1+T2.2→T2.7 (provider adapters require the shared coordinator and durable provider/tab/session binding); T2.1+T2.2+T2.7→T2.3 (finalized media and persisted identity must exist before automatic enqueue; T2.7→T2.3 also serializes their shared `extension/src/background.ts` edit); T2.2+T2.3→T2.4 (T2.3 persists the `recordingId` required by the processing gate); T2.4→T2.5 (verified success precedes launch); T2.2+T2.3+T2.4+T2.7→T2.8 (status presentation needs persisted state, upload/processing outcomes, and adapter completion errors).
- Verified shared-file conflict: T2.1, T2.7, T2.3, T2.4, and T2.5 all modify `extension/src/background.ts`; serialize them as T2.1→T2.7→T2.3→T2.4→T2.5. T2.3→T2.4 is both a file-conflict edge and the real `recordingId` producer prerequisite; T2.4→T2.5 remains the real success-before-launch prerequisite.
- External dependencies named by design: `task_11001b7f5b084e09` upload result/failure contract and `task_6a271652b2c34130` protected meeting review/playback. Portal authentication/login remains a separate contract consumed by the protected review integration in T1.6/T2.6; it does not own the existing meeting-status route's owner check. T1.4 (#613) tests that route, and T2.4 (#622) implements authorization through `_get_authorized_meeting`.
- Independent RED tasks T1.1–T1.7 and T1.9 can proceed concurrently; T1.8 follows T1.1/T1.2. Implementation tasks remain parallel except explicit mapping/status/launch/UI dependencies. T1.6/T2.6 wait for existing protected playback/API contracts; its seams are `get_transcript`, `get_playback_manifest`, and `_get_authorized_meeting` in `backend/app/meetings/router.py`.
- T3.1 depends on every feature-flow GREEN task, T2.1–T2.8, so end-to-end validation cannot precede authenticated review integration (T2.6), provider adapter wiring (T2.7), or visible status/recovery (T2.8). T3.2 follows T3.1, so final configured validation includes all implementations, the migration, both provider paths, and status presentation.

## Assumptions and unresolved implementation checks

- Extension test scripts and `fast-check` are present in `extension/package.json`; no test-runner setup task is warranted by the checked-in package declaration. A developer must still verify the runner is executable in their worktree before proceeding.
- Design's intended module paths are canonical; exact existing test placement/export names should be verified before code changes. If an indicated seam does not exist, use its nearest existing module test and retain the specified behavior, not a speculative new production API.
- No backend SQL schema migration or Compose change is expected. The extension IndexedDB v1→v2 migration is required by the approved design and covered by T1.2/T2.2.
- The Teams completion adapter is in scope; a Teams media-capture pipeline is neither presumed to exist nor added by this plan. No visual redesign, consent, retention, or upload-defect remediation is included.

## Delivery reconciliation — 2026-11-12

APX parent `task_9e74a2d278d648ad` resumes the existing PR #703, not a new parallel implementation. The #709 amendment was approved and merged in PR #719 (unchanged approved artifact blob `4ba0841067fa9197c199bd261af336d3028cc3da`); historical pending wording below is provenance, not a renewed approval gate.

T1.1/#610 and T2.1/#619 form one RED→GREEN delivery on the existing branch. The approved design requires durable transactional claims, so the capture-store prerequisite from T1.2/#611 and T2.2/#620 is included in this branch; those broader identity/review tasks remain open until all their criteria pass. No product scope or acceptance criterion is removed. Remaining upload/status/review wiring stays in its existing tasks.

Executed listener RED at `c9bf45c`: 2 passed / 2 failed; Stop+tab-close emitted two stop messages, and meeting-ended replaced active recording state with idle. Each property is configured for 100 cases (failing properties stop and shrink at the first counterexample). Candidate GREEN adds durable capture records and claims; tests alone do not establish real capture/upload delivery. Before integration verify error/restart windows, obsolete capture records, full regression/typecheck/build, and browser behavior. No task is closed by this reconciliation.

## Bounded finalization candidate — 2026-11-12

APX `task_d9a886135dae47b0`, PR #703, T1.1/#610 + T2.1/#619, R1.1–R1.5/R5.2. This is implementation evidence, not merge or product acceptance. T1.2/#611 and T2.2/#620 remain partial/open (full ingestion identity mapping and review claims are not delivered here).

- The transactional `finalizing` record is now a durable delivery intent. Worker startup and the existing alarm replay it after a crash or rejected send; every stop carries its session ID. Replays may repeat transport messages, but offscreen stops only the matching recorder once. Tests distinguish delivery attempts from actual media finalization.
- Offscreen refuses missing/foreign stop identities, retains a stop requested during capture initialization, waits for final chunk transaction commits, and marks finalized media `upload_pending`. Failed start/capture retains chunks and the original identity with a local `captureError` marker; failed captures are excluded from active-tab lookup and cannot poison a subsequent capture on that tab.
- Live legacy session bindings can stop without synthesizing a meeting/completion identity. Additive v1 migration, blocked upgrade retry and versionchange preserve old chunks. Meeting-ended/discovery cannot detach an active session. Late completion/error for another session does not reset the current capture projection.
- Validation: `cd extension && npm run test` — 161 passed in 34 files; `npm run typecheck` and `npm run build` passed. Existing generated listener/DB properties remain at 100 cases. Added crash-before-dispatch, rejected delivery/restart, failed capture, legacy Stop/close, foreign/duplicate offscreen stop, stop-during-start, committed final chunk and blocked migration coverage.
- Browser smoke: unpacked production build loaded in an isolated Chromium profile; panel login rendered without page errors; a synthetic durable handle survived meeting-ended and real `tabs.onRemoved` persisted the same session/meeting finalization intent. This is **not** real Meet/Teams media capture or upload validation. Screenshot and runner retained with the APX task evidence.
- Limits: full capture→upload→processing→review remains undelivered. Recovery after media is finalized but before upload enqueue belongs to the subsequent upload bridge; no full durable queue/recordingId/review claim completion is asserted. The repository's `test:e2e` setup writes to shared local PostgreSQL/MinIO and starts port 8000 with auth disabled, so it was not run against the owner's environment. Ansel retains candidate review, isolated integration validation and product acceptance; PR remains draft until those conditions are verified.

## Scoped corrective delivery — PR #823 (2026-11-12)

- Parent APX task: `task_9e74a2d278d648ad`. Continues T1.7 (#616) with the ambiguous-handle error portion of T2.7 (#625) and minimal Side Panel feedback from T2.8 (#626). Existing approved requirements/design/task plan apply; no new scope or approval is implied.
- Ansel reproduced both behavioral RED failures, then corrected the durable resolver: multiple active candidates are marked `captureError` in one committed transaction before reporting ambiguity. No candidate is selected or stopped; identity, chunks and unrelated captures are retained. Repeated/concurrent close and worker restart cannot select a remaining ambiguous candidate.
- The Side Panel reads the selected session's durable capture error on mount and while open, shows a non-successful alert, recovers it on reopen and hides it when switching to another session. It does not implement the rest of the outcome/retry/review UI.
- Validation: 172 tests in 35 files pass, including both previous RED cases, concurrent/unprojected ambiguity, preserved media chunks and four durable feedback tests; extension typecheck/build and diff check pass. Browser check uses the production panel build over an isolated localhost fixture with synthetic Chrome state and real browser IndexedDB: error appears, survives reload and disappears for a different healthy session. This is not a real Chrome capture or extension-service-worker end-to-end check.
- T2.7/T2.8 remain partial; #821 remains open and was not merged or copied. No complete upload/processing/review flow, actual Teams media capture, integration or product acceptance is claimed. Merge remains reserved; no task/issue is closed by this entry.

## Publication tracking

Prior approved task-plan snapshot: `c0eb360fdb964c00bc76f1b72444022a10dfa00a` (Mira APPROVED, 2026-10-31). This is the scoped #709 amendment candidate to T1.1/T2.1; the candidate awaits Mira's independent audit, and `.config.spectra` phase `complete` records authorship only. The plan continues to derive from approved requirements `98e52824d5b8f30f5e1b189c3d4f2ce5aed926f2` and corrected design `a477c0bde2ac3f140d04020af06afa05fb96c4f6` (Mira APPROVED). GitHub issues #610–#628 map the 19 tasks in milestone `chrome-recording-completion` (#17); this amendment does not create, renumber, or publish implementation tasks. Per Ansel's coordination decision, APX card creation was deferred until real responsible agents and dependency readiness were available; the T1.8 row below now records its subsequently assigned delivery and draft PR without claiming implementation or integration.

| Task | GitHub issue | APX card |
|---|---:|---|
| T1.1 | #610 | Pending — APX assignment resolution |
| T1.2 | #611 | Pending — APX assignment resolution |
| T1.3 | #612 | Pending — APX assignment resolution |
| T1.4 | #613 | Pending — APX assignment resolution |
| T1.5 | #614 | Pending — APX assignment resolution |
| T1.6 | #615 | Pending — APX assignment resolution |
| T1.7 | #616 | Pending — APX assignment resolution |
| T1.8 | #617 | `task_dd6b09519f754272` — RED tests in draft PR #826 (`0a110ba`); reviewed, not merged or product-accepted |
| T1.9 | #618 | Pending — APX assignment resolution |
| T2.1 | #619 | Pending — APX assignment resolution |
| T2.2 | #620 | Pending — APX assignment resolution |
| T2.3 | #621 | Pending — APX assignment resolution |
| T2.4 | #622 | Pending — APX assignment resolution |
| T2.5 | #623 | Pending — APX assignment resolution |
| T2.6 | #624 | Pending — APX assignment resolution |
| T2.7 | #625 | Pending — APX assignment resolution |
| T2.8 | #626 | Pending — APX assignment resolution |
| T3.1 | #627 | Pending — APX assignment resolution |
| T3.2 | #628 | Pending — APX assignment resolution |
