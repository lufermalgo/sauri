# Implementation Plan — Chrome Recording Completion

## Upstream traceability

- Approved baseline snapshot: `PRODUCT_BASELINE.md` commit `4953b3b4b8a058fd4738342307cc50bfd66814f1`, blob `c6f9ef9bf3fac9eac23763e25e25e1089a16c446` (context only; it does not authorize this extension delta).
- Requirements: `.spectra/specs/chrome-recording-completion/requirements.md`, Mira APPROVED, snapshot `98e52824d5b8f30f5e1b189c3d4f2ce5aed926f2`, PR #605 (not merged at planning time).
- Design: `.spectra/specs/chrome-recording-completion/design.md`, Mira APPROVED, amended snapshot `bf4ca181e70e8d97088a23a221438663a01d0b25`, PR #608.
- Owner direction: 2026-10-30; requirements contain traceability to the source direction and Cyrus reconciliation.
- Import provenance: requirements and `.config.spectra` remain byte-identical to the approved source worktree; the design matches exact approved snapshot `a477c0bde2ac3f140d04020af06afa05fb96c4f6` (Git blob `ec67cad96b6907911f2f335b17917753993d6937`, SHA-256 `16bbfc35dcaf3a4ccc74b8e21790ca12faf2be30d51591c03f6bde465383ba6a`).

## Summary of phases

| Phase | Description | Tasks | Dependencies |
|---|---|---|---|
| 1 | RED tests for lifecycle, durable-state migration, provider adapters, and protected review invariants | T1.1–T1.9 | T1.8 follows T1.1/T1.2; T1.6 follows named API/playback prerequisites; other RED tests independent |
| 2 | GREEN lifecycle, IndexedDB v2, provider adapters, status presentation, and review flow | T2.1–T2.8 | Matching RED; true upload/API/login/playback prerequisites where stated |
| 3 | End-to-end integration and changed-contract security verification | T3.1–T3.2 | Extension GREEN tasks; upstream portal/API and playback tasks |

**Validation environment:** extension tests/build/typecheck use the existing scripts in `extension/package.json`: `cd extension && npm run test -- <test-file>`, `npm run typecheck`, `npm run build`, and `npm run test:e2e`. Property tests use the already-declared `fast-check` dependency and must run at ≥100 generated cases per property. If npm dependencies/test runner are not available in a fresh worktree, resolve that environment prerequisite before implementation; do not skip RED execution. Use synthetic recordings, IDs, and server responses only. Frontend and backend commands apply only if those surfaces/contracts are actually changed: `cd frontend && npm run test/typecheck/build`; `cd backend && pytest` (or the configured narrow pytest path).

## Phase 1: Required RED tests

### Tarea 1.1: Test convergence of Stop and captured-tab-close

**Archivo:** `extension/src/background.test.ts`; seam `completeRecording(sessionId, trigger)` in `extension/src/background.ts`
**Acción:** Add required property-based coverage at the design's named completion coordinator `completeRecording(sessionId, trigger)` for Stop, captured-tab-close, both event orders, duplicates, and meeting-ended-only input. Assert one finalization claim at most once per `sessionId`, and zero claims for meeting-ended alone; use `fast-check` sequences with ≥100 cases and synthetic IDs.
**Criterio de Completado:** `cd extension && npm run test -- src/background.test.ts` fails against current behavior for the missing transition semantics and reports a counterexample; the test contains ≥100 generated cases.
**Dependencias:** Ninguna.

### Tarea 1.2: Test durable identity conservation and atomic completion claims

**Archivo:** `extension/src/recording-db.test.ts`; persistence seam `openDB()` and IndexedDB upgrade/transaction boundaries in `extension/src/recording-db.ts`
**Acción:** With a populated synthetic v1 `sauri-recordings` fixture, call `openDB()` to exercise the v1→v2 upgrade. Assert the existing `chunks` store, key path, `by_session` index, and chunk rows remain readable; the new `completion_records` store is keyed by `sessionId` and has a non-unique `capturedTabId` index; no completion rows are synthesized for legacy chunks. Exercise durable `RecordingCompletion` identity (`provider`, `sessionId → meetingId → recordingId`), retry/reload preservation, response mismatch rejection, and transactional duplicate finalization/launch claims. Include `blocked`/`versionchange` handling without data loss.
**Criterio de Completado:** `cd extension && npm run test -- src/recording-db.test.ts` fails against v1 behavior and verifies the v1→v2 migration, preserved chunk data/indexes, new completion store/index, stable identity, mismatched response, and transactional claim cases.
**Dependencias:** Ninguna.

### Tarea 1.3: Test truthful upload outcome mapping

**Archivo:** `extension/src/upload-queue.test.ts`
**Acción:** At `uploadRecording` / `processUploadQueue` result seams, cover success only for a valid successful response with the same recording mapping; cover network, non-2xx, and invalid-response outcomes as failure/unavailable, never success. Assert retries retain sessionId and meetingId.
**Criterio de Completado:** `cd extension && npm run test -- src/upload-queue.test.ts` fails for the specified missing truthful result contract using synthetic responses.
**Dependencias:** Ninguna.

### Tarea 1.4: Test owner-authorized status and same-meeting processing success

**Archivo:** `extension/src/background.test.ts`; seams `completeRecording(sessionId, trigger)` in `extension/src/background.ts` and `get_meeting_endpoint` for `GET /api/v1/meetings/{meeting_id}` in `backend/app/meetings/router.py`; `backend/tests/meetings/test_get_meeting_property.py`
**Acción:** At `completeRecording(sessionId, trigger)`, cover each documented `process_state` mapping and the authenticated status/transcript/playback-manifest gate. Assert completed without transcript, usable video, or matching meeting/recording never produces `processing_succeeded`; pending and failed remain distinct. At the existing `get_meeting_endpoint`, verify `_get_authorized_meeting` enforces ownership: the owner receives status, unauthenticated access returns 401, and a different authenticated user requesting an existing synthetic meeting receives 404 with no status/recording fields. Use synthetic DB fixtures and users.
**Criterio de Completado:** `cd extension && npm run test -- src/background.test.ts` and `cd backend && pytest tests/meetings/test_get_meeting_property.py` fail on the missing completion or owner-authorization gates; backend assertions cover owner success, unauthenticated 401, and non-owner 404/no status disclosure.
**Dependencias:** Ninguna.

### Tarea 1.5: Test review launch gating and at-most-one recovery

**Archivo:** `extension/src/background.test.ts`; service-worker review-launch path in `extension/src/background.ts`, including the design-specified `chrome.tabs.create` boundary
**Acción:** Exercise the persisted review-launch claim/reconciliation path leading to `chrome.tabs.create`. Cover concurrent completion signals, retries, worker restart with launch pending, and discovery of a matching canonical Sauri target; assert at most one tab creation and only after `processing_succeeded`. Use synthetic IDs and Chrome API boundary fixtures.
**Criterio de Completado:** `cd extension && npm run test -- src/background.test.ts` fails on duplicate launch or launch before verified success; the test covers the named `chrome.tabs.create` boundary, pending-marker reconciliation, and matching-target discovery.
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

**Archivo:** `extension/src/content.ts`, `extension/src/background.ts`, and pure state logic in `extension/src/core/`
**Acción:** Route explicit Stop and closure of the specifically associated captured tab to `completeRecording(sessionId, trigger)`; use one atomic transition/finalization claim, ignore meeting-ended alone, and leave media finalization in the existing capture/offscreen owner.
**Criterio de Completado:** T1.1 passes with ≥100 property cases; `cd extension && npm run typecheck` passes.
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
**Dependencias:** T1.3, T1.8, T2.1, T2.2, `task_11001b7f5b084e09` (separate upload failure/result-contract repair).

### Tarea 2.4: Enforce owner authorization for status and gate processing success on both protected assets

**Archivo:** `backend/app/meetings/router.py:get_meeting_endpoint`, `extension/src/background.ts`, and the status mapping/bridge under `extension/src/core/`
**Acción:** On the existing `GET /api/v1/meetings/{meeting_id}` handler, enforce meeting ownership for the authenticated user using the existing meetings authorization boundary; return 404 for a non-owner without disclosing meeting status or recording fields, while preserving 401 for unauthenticated requests. Do not add a parallel route. In the extension status bridge, map documented `process_state` values; for `completed`, require the persisted `meetingId`, matching `recordingId`, protected transcript availability, and usable playback-manifest video before persisting `processing_succeeded`. Preserve unavailable/auth-required, failed, and non-ready states without inventing retry intervals or limits. Publish per-recording status for T2.8; do not implement a speculative UI component.
**Criterio de Completado:** T1.4 passes with owner success, unauthenticated 401, and non-owner 404/no status disclosure; `cd backend && pytest tests/meetings/test_get_meeting_property.py` and `cd extension && npm run test -- src/background.test.ts` pass; `cd extension && npm run typecheck` passes. The status bridge emits the matching durable per-recording state consumed by T2.8.
**Dependencias:** T1.4, T2.2, `task_6a271652b2c34130` (protected transcript/playback asset contract).

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
- Actual implementation prerequisites: T2.1+T2.2→T2.3 (finalized media and persisted identity must exist before automatic enqueue); T2.2→T2.4 (status is bound to the persisted mapping); T2.4→T2.5 (verified success precedes launch); T2.1+T2.2→T2.7 (provider adapters require the shared coordinator and durable provider/tab/session binding); T2.2+T2.3+T2.4+T2.7→T2.8 (status presentation needs persisted state, upload/processing outcomes, and adapter completion errors).
- External dependencies named by design: `task_11001b7f5b084e09` upload result/failure contract and `task_6a271652b2c34130` protected meeting review/playback. Portal authentication/login remains a separate contract consumed by the protected review integration in T1.6/T2.6; it does not own the existing meeting-status route's owner check. T1.4 (#613) tests that route, and T2.4 (#622) implements authorization through `_get_authorized_meeting`.
- Independent RED tasks T1.1–T1.7 and T1.9 can proceed concurrently; T1.8 follows T1.1/T1.2. Implementation tasks remain parallel except explicit mapping/status/launch/UI dependencies. T1.6/T2.6 wait for existing protected playback/API contracts; its seams are `get_transcript`, `get_playback_manifest`, and `_get_authorized_meeting` in `backend/app/meetings/router.py`.
- T3.1 depends on every feature-flow GREEN task, T2.1–T2.8, so end-to-end validation cannot precede authenticated review integration (T2.6), provider adapter wiring (T2.7), or visible status/recovery (T2.8). T3.2 follows T3.1, so final configured validation includes all implementations, the migration, both provider paths, and status presentation.

## Assumptions and unresolved implementation checks

- Extension test scripts and `fast-check` are present in `extension/package.json`; no test-runner setup task is warranted by the checked-in package declaration. A developer must still verify the runner is executable in their worktree before proceeding.
- Design's intended module paths are canonical; exact existing test placement/export names should be verified before code changes. If an indicated seam does not exist, use its nearest existing module test and retain the specified behavior, not a speculative new production API.
- No backend SQL schema migration or Compose change is expected. The extension IndexedDB v1→v2 migration is required by the approved design and covered by T1.2/T2.2.
- The Teams completion adapter is in scope; a Teams media-capture pipeline is neither presumed to exist nor added by this plan. No visual redesign, consent, retention, or upload-defect remediation is included.

## Publication tracking

Mira approved the prior task-plan snapshot `56e36feff04406cda3435ac00a0621aec3c1b3b7`; this scoped amendment derives from the corrected design snapshot `a477c0bde2ac3f140d04020af06afa05fb96c4f6` (Mira APPROVED) and awaits focused tasks audit. GitHub issues #610–#628 remain the mapping for this plan in milestone `chrome-recording-completion` (#17). APX card creation is pending real owners and dependency readiness; no card IDs are claimed here.

| Task | GitHub issue | APX card |
|---|---:|---|
| T1.1 | #610 | Pending — APX assignment resolution |
| T1.2 | #611 | Pending — APX assignment resolution |
| T1.3 | #612 | Pending — APX assignment resolution |
| T1.4 | #613 | Pending — APX assignment resolution |
| T1.5 | #614 | Pending — APX assignment resolution |
| T1.6 | #615 | Pending — APX assignment resolution |
| T1.7 | #616 | Pending — APX assignment resolution |
| T1.8 | #617 | Pending — APX assignment resolution |
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
