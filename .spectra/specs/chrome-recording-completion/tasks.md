# Implementation Plan — Chrome Recording Completion

## Upstream traceability

- Approved baseline snapshot: `PRODUCT_BASELINE.md` commit `4953b3b4b8a058fd4738342307cc50bfd66814f1`, blob `c6f9ef9bf3fac9eac23763e25e25e1089a16c446` (context only; it does not authorize this extension delta).
- Requirements: `.spectra/specs/chrome-recording-completion/requirements.md`, Mira APPROVED, snapshot `98e52824d5b8f30f5e1b189c3d4f2ce5aed926f2`, PR #605 (not merged at planning time).
- Design: `.spectra/specs/chrome-recording-completion/design.md`, Mira APPROVED, snapshot `109dec118438400fa6a634fd6b506a832995ff65`, PR #608 (not merged at planning time).
- Owner direction: 2026-10-30; requirements contain traceability to the source direction and Cyrus reconciliation.
- Import provenance: upstream approved requirements, design and `.config.spectra` were copied byte-identically from worktree `feature-chrome-recording-completion-design`; SHA-256 respectively `ad6208cc61fd8472ee2e1a257eab75ab0e67cf1ac0e35ccc670f640f852f0f6e`, `b101c0cb5b22250faba1bd5cee7309d8f865a4452ebabc1ba4415df9329101c1`, and `b1ebd08a08ba54d6cbb7effd66266ee3b37331f930f68651cb6265a8a4985af2`.

## Summary of phases

| Phase | Description | Tasks | Dependencies |
|---|---|---|---|
| 1 | RED tests for extension lifecycle and protected review invariants | T1.1–T1.9 | Independent except tests waiting on named upstream API/playback prerequisites |
| 2 | GREEN extension lifecycle, status presentation, and review flow | T2.1–T2.8 | Matching RED; upstream upload/API/login/playback prerequisites where stated |
| 3 | End-to-end integration and changed-contract security verification | T3.1–T3.2 | Extension GREEN tasks; upstream portal/API and playback tasks |

**Validation environment:** extension tests/build/typecheck use the existing scripts in `extension/package.json`: `cd extension && npm run test -- <test-file>`, `npm run typecheck`, `npm run build`, and `npm run test:e2e`. Property tests use the already-declared `fast-check` dependency and must run at ≥100 generated cases per property. If npm dependencies/test runner are not available in a fresh worktree, resolve that environment prerequisite before implementation; do not skip RED execution. Use synthetic recordings, IDs, and server responses only. Frontend and backend commands apply only if those surfaces/contracts are actually changed: `cd frontend && npm run test/typecheck/build`; `cd backend && pytest` (or the configured narrow pytest path).

## Phase 1: Required RED tests

### Tarea 1.1: Test convergence of Stop and captured-tab-close

**Archivo:** `extension/src/core/recording-completion.test.ts` (or colocated core test for the introduced transition module)
**Acción:** Add required property-based coverage at the core transition seam for Stop, captured-tab-close, both event orders, duplicates, and meeting-ended-only input. Assert a single `sessionId` finalization claim at most once, and zero claims for meeting-ended alone; use `fast-check` sequences with ≥100 cases.
**Criterio de Completado:** `cd extension && npm run test -- src/core/recording-completion.test.ts` fails against current behavior for the missing transition semantics and reports the counterexample; the test contains ≥100 generated cases.
**Dependencias:** Ninguna.

### Tarea 1.2: Test durable identity conservation and atomic completion claims

**Archivo:** `extension/src/recording-db.test.ts` (or adjacent test for the persistence API)
**Acción:** Exercise the `sessionId → meetingId → recordingId` record and transactional claim/update seams with synthetic data. Assert persisted `meetingId` survives retry/reload, response mismatch is rejected, and concurrent duplicate completion claims cannot create a second identity/finalization.
**Criterio de Completado:** `cd extension && npm run test -- src/recording-db.test.ts` fails on missing durable mapping/atomic claim behavior and includes concurrent duplicate claim and mismatched-response cases.
**Dependencias:** Ninguna.

### Tarea 1.3: Test truthful upload outcome mapping

**Archivo:** `extension/src/upload-queue.test.ts`
**Acción:** At `uploadRecording` / `processUploadQueue` result seams, cover success only for a valid successful response with the same recording mapping; cover network, non-2xx, and invalid-response outcomes as failure/unavailable, never success. Assert retries retain sessionId and meetingId.
**Criterio de Completado:** `cd extension && npm run test -- src/upload-queue.test.ts` fails for the specified missing truthful result contract using synthetic responses.
**Dependencias:** Ninguna.

### Tarea 1.4: Test processing success requires same-meeting transcript and video

**Archivo:** `extension/src/core/recording-completion.test.ts` and module-adjacent coordinator test for status bridge
**Acción:** Cover every documented process_state mapping and the authenticated status/transcript/playback-manifest gate. Assert completed without transcript, usable video, or matching meeting/recording never produces `processing_succeeded`; pending and failed remain distinct.
**Criterio de Completado:** `cd extension && npm run test -- src/core/recording-completion.test.ts` fails on any absent success gate and includes synthetic missing-asset and identity-mismatch cases.
**Dependencias:** Ninguna.

### Tarea 1.5: Test review launch gating and at-most-one recovery

**Archivo:** `extension/src/background.test.ts` (or colocated background coordinator test)
**Acción:** Exercise `completeRecording`/review-launch coordinator and `chrome.tabs.create` test boundary. Cover concurrent signals, repeated retries, worker restart with launch pending, and matching-target discovery; assert at most one tab creation and only for processing success.
**Criterio de Completado:** `cd extension && npm run test -- src/background.test.ts` fails on duplicate launch or launch before verified success; tests use synthetic IDs and Chrome API boundary fixtures.
**Dependencias:** Ninguna.

### Tarea 1.6: Test authorization boundary for transcript and playback endpoints

**Archivo:** `backend/tests/meetings/test_review_asset_authorization.py`; seams `backend/app/meetings/router.py:get_transcript`, `get_playback_manifest`, `_get_authorized_meeting`
**Acción:** Write RED endpoint tests for `GET /api/v1/meetings/{meeting_id}/transcript` and `GET /api/v1/meetings/{meeting_id}/playback`. Verify unauthenticated and non-owner users receive no transcript/video asset, and an authorized owner receives only assets for the requested synthetic meeting. Keep review rendering/playback behavior owned by `task_6a271652b2c34130`.
**Criterio de Completado:** `cd backend && pytest tests/meetings/test_review_asset_authorization.py` fails if either named handler returns protected assets without `get_current_user` authentication and `_get_authorized_meeting` authorization; fixtures use synthetic IDs and media.
**Dependencias:** `task_dfcb314806c04033` (portal API/login contract), `task_6a271652b2c34130` (protected review destination and endpoint contract).

### Tarea 1.7: Test scope boundary for Teams and excluded changes

**Archivo:** `extension/src/background.tab-close.test.ts`; seam `chrome.runtime.onMessage` handling of `meeting-ended` and captured-tab lifecycle
**Acción:** Add assertions that a meeting-ended-only message does not call `completeRecording` or stop capture and that tab-close completion is limited to the currently associated supported capture context; do not assert or implement new Teams capture capability.
**Criterio de Completado:** `cd extension && npm run test -- src/background.tab-close.test.ts` fails if meeting-ended triggers finalization or an unsupported Teams context is treated as an active supported capture; fixtures use synthetic tab/session IDs.
**Dependencias:** Ninguna.

### Tarea 1.8: Test automatic enqueue of finalized audio and video

**Archivo:** `extension/src/background.test.ts`; seam `completeRecording(sessionId, trigger)` → existing upload-queue enqueue boundary
**Acción:** Add a required RED integration test that completes a synthetic recording and asserts the finalized audio and video are automatically enqueued once with the existing `sessionId` and persisted `meetingId`; assert no separate user upload action is required and duplicate trigger does not enqueue a second recording.
**Criterio de Completado:** `cd extension && npm run test -- src/background.test.ts` fails before implementation because completion does not yet enqueue the finalized media automatically; assertion verifies both media references and stable IDs.
**Dependencias:** T1.1, T1.2.

### Tarea 1.9: Test user-visible truthful upload and processing states

**Archivo:** `extension/src/panel/components/RecordingCompletionStatus.test.tsx`; seam `RecordingCompletionStatus` rendered in `SidePanelApp`
**Acción:** Add RED component tests for persisted per-recording `uploading`, `upload_succeeded`, `upload_failed`/`upload_outcome_unavailable`, `processing`, `processing_failed`, `processing_assets_unavailable`, and `processing_succeeded` states. Verify success is never shown for in-progress, failed, unavailable, stale, or different-recording state.
**Criterio de Completado:** `cd extension && npm run test -- src/panel/components/RecordingCompletionStatus.test.tsx` fails before implementation and asserts visible status text/role for each outcome against synthetic recording IDs.
**Dependencias:** Ninguna.

## Phase 2: GREEN implementation

### Tarea 2.1: Implement one idempotent completion transition for authorized triggers

**Archivo:** `extension/src/content.ts`, `extension/src/background.ts`, and pure state logic in `extension/src/core/`
**Acción:** Route explicit Stop and closure of the specifically associated captured tab to `completeRecording(sessionId, trigger)`; use one atomic transition/finalization claim, ignore meeting-ended alone, and leave media finalization in the existing capture/offscreen owner.
**Criterio de Completado:** T1.1 passes with ≥100 property cases; `cd extension && npm run typecheck` passes.
**Dependencias:** T1.1.

### Tarea 2.2: Persist the stable recording identity mapping and atomic state

**Archivo:** `extension/src/recording-db.ts` and its existing module tests
**Acción:** Persist the completion record keyed by `sessionId`, allocate and persist one `meetingId` before network I/O, validate/persist the server `recordingId`, and transact completion/launch claims so duplicate events and restarts reconcile the same mapping. Persist only opaque IDs and bounded non-sensitive status/error summaries.
**Criterio de Completado:** T1.2 passes; `cd extension && npm run typecheck` passes; tests prove retry/restart keep the exact synthetic mapping.
**Dependencias:** T1.2.

### Tarea 2.3: Consume truthful upload queue results without duplicating upload repair

**Archivo:** `extension/src/upload-queue.ts`, `extension/src/background.ts`
**Acción:** After `completeRecording(sessionId, trigger)` successfully finalizes both assets, enqueue those finalized media references exactly once through the existing upload queue with persisted `sessionId` and `meetingId`; persist returned `recordingId`, reflect success only from a valid success result, and integrate (not implement) the separately owned upload-failure contract.
**Criterio de Completado:** T1.3 and T1.8 pass; both media assets are automatically enqueued without user action, retries retain the same identity, and failure/unavailable queue results never appear as success.
**Dependencias:** T1.3, T1.8, T2.1, T2.2, `task_11001b7f5b084e09` (separate upload failure/result-contract repair).

### Tarea 2.4: Gate processing success on authenticated status and both protected assets

**Archivo:** `extension/src/background.ts`, status bridge and pure mapping under `extension/src/core/`; backend meeting/status owner only if the existing authenticated read contract is absent
**Acción:** Map documented `process_state` values; for `completed`, require authenticated status for persisted `meetingId`, matching `recordingId`, protected transcript availability, and usable video in playback manifest before persisting `processing_succeeded`. Preserve unavailable/auth-required, failed, and non-ready states without inventing retry intervals or limits. Publish each per-recording transition for the side-panel status component in T2.8; use portal API/login contract rather than duplicating its fix.
**Criterio de Completado:** T1.4 passes; status bridge emits the matching persisted recording state for T2.8 to render; `cd extension && npm run typecheck` passes; any changed backend endpoint also passes the configured `cd backend && pytest <matching test path>` and authorization tests.
**Dependencias:** T1.4, T2.2, `task_dfcb314806c04033` (authenticated API/login contract), `task_6a271652b2c34130` (status/assets review API contract).

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

### Tarea 2.7: Keep event and capability scope within approval

**Archivo:** `extension/src/content.ts`, `extension/src/background.ts`, existing capture capability seam
**Acción:** Wire completion only for capture contexts that provide the existing recording identity and finalized media; do not claim to add Teams capture, treat meeting-ended as a trigger, or introduce redesign, consent, or retention changes.
**Criterio de Completado:** T1.7 passes; `cd extension && npm run typecheck` passes and the change adds no new capture capability or excluded product flow.
**Dependencias:** T1.7, T2.1.

### Tarea 2.8: Present truthful per-recording outcomes in the existing side panel

**Archivo:** `extension/src/panel/components/RecordingCompletionStatus.tsx`, its colocated test, `extension/src/panel/SidePanelApp.tsx`
**Acción:** Render the persisted completion status received from the worker in the existing side panel, keyed by `sessionId`/`meetingId`. Display distinct user-visible in-progress, success, failure, and unavailable states for upload and processing; do not show stale state from a different recording or claim review readiness before `processing_succeeded`. This is status presentation only, not a visual redesign.
**Criterio de Completado:** T1.9 passes for every specified visible state and stale/different-recording case; `cd extension && npm run typecheck` passes.
**Dependencias:** T1.9, T2.2, T2.3, T2.4.

## Phase 3: Integration and validation

### Tarea 3.1: Verify synthetic completion-to-review end-to-end flow

**Archivo:** `extension/tests/e2e/`
**Acción:** Add E2E coverage of synthetic capture completion through upload/status reconciliation to one authenticated Sauri review target, including reload/restart and duplicate completion handling. Mock external network only at test boundaries; use no live capture or real meeting data.
**Criterio de Completado:** `cd extension && npm run test:e2e` passes with a single matching target opened only after confirmed processing success; pending/failed/unavailable cases do not open a ready review tab.
**Dependencias:** T2.1–T2.8, `task_11001b7f5b084e09`, `task_dfcb314806c04033`, `task_6a271652b2c34130`.

### Tarea 3.2: Run configured validation for the changed product surfaces

**Archivo:** Changed extension/frontend/backend surface test suites
**Acción:** Run the design's configured commands only for surfaces actually changed: extension test/typecheck/build/E2E; frontend test/typecheck/build if changed; backend pytest if changed. Record exact successful outputs and fix regressions before implementation PR.
**Criterio de Completado:** Every applicable configured validation command exits successfully on the implementation candidate; unmodified surfaces are not run as an invented gate.
**Dependencias:** T3.1, T2.6, T2.7, T2.8.

## Dependency graph and rationale

- Mandatory RED→GREEN edges: T1.1→T2.1; T1.2→T2.2; T1.3→T2.3; T1.4→T2.4; T1.5→T2.5; T1.6→T2.6; T1.7→T2.7; T1.9→T2.8. T1.8 verifies T2.3 automatic enqueue, in addition to the upload result tests in T1.3.
- Actual implementation prerequisites: T2.1+T2.2→T2.3 (finalized media and persisted identity must exist before automatic enqueue); T2.2→T2.4 (status is bound to persisted mapping); T2.4→T2.5 (success gate precedes launch); T2.1→T2.7 (scope is applied to completion wiring); T2.2+T2.3+T2.4→T2.8 (status presentation needs persisted state and upload/processing outcomes).
- External dependencies are the existing tracked work: `task_11001b7f5b084e09` upload result/failure contract; `task_dfcb314806c04033` portal authenticated API/login; `task_6a271652b2c34130` protected meeting review/playback. These tasks are not duplicated here.
- Independent RED tasks T1.1–T1.5, T1.7–T1.9 can proceed concurrently; implementation tasks remain parallel except for the explicit mapping/status/launch dependencies. T1.6/T2.6 wait for existing portal/playback contracts; the test seam is fixed to `get_transcript`, `get_playback_manifest`, and `_get_authorized_meeting` in the meetings router.
- T3.1 depends on every feature-flow GREEN task, T2.1–T2.8, so its end-to-end flow cannot precede authenticated review integration (T2.6), supported-context event wiring (T2.7), or visible status presentation (T2.8). T3.2 follows T3.1 and every GREEN task so final configured validation cannot omit any implementation.

## Assumptions and unresolved implementation checks

- Extension test scripts and `fast-check` are present in `extension/package.json`; no test-runner setup task is warranted by the checked-in package declaration. A developer must still verify the runner is executable in their worktree before proceeding.
- Design's intended module paths are canonical; exact existing test placement/export names should be verified before code changes. If an indicated seam does not exist, use its nearest existing module test and retain the specified behavior, not a speculative new production API.
- Current backend schema needs no migration unless implementation investigation proves existing durable state insufficient; no Compose change is expected.
- Teams capture capability is explicitly not presumed or added by this plan. No visual redesign, consent, retention, or upload-defect remediation is included.
