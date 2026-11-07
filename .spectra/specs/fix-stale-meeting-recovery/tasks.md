# Implementation Tasks — Guarded Manual Recovery for Stale Meetings

## Upstream and scope

This plan is derived only from the approved snapshots below. It plans backend code/tests and does **not** authorize recovery against live meetings, the one-meeting operational pilot, deployment, or release.

- Approved baseline: `PRODUCT_BASELINE.md` at `85b603ada14996842d913cfbbed4bcffe9fe54c5` (blob `2337a46b2ba78ef4364e23a86df9918db621c881`). The baseline supports later review of recordings/transcripts; it does not define recovery.
- Approved bugfix: `.spectra/specs/fix-stale-meeting-recovery/bugfix.md`, commit `f0c076e799fc46cf3b843fbade59f0a4154cb7a6`, blob `7cac06232e96bdc76239a1e9cb4a5495c7623663`; Mira-approved and merged by PR #671. Manual initiation, the single-meeting first pilot and data/privacy boundaries come from Fer's explicit decision recorded on `task_31c25607a8684d7b`.
- Approved design base: `.spectra/specs/fix-stale-meeting-recovery/design.md`, commit `4673e6e5f2e6c81c4986367bd15fc72867ae996a`, blob `835f44e8d7b41d6b78024f63bf20bcad76fac8e8`; Mira-approved and merged by PR #689.
- Approved design amendment: same artifact, commit `4473cfd0054a96c531673d036e8066c3d0f8b2b5`, blob `5417a8ceedd91b703a0a4dc6a321876781a2bd9b`; Mira-approved and merged via PR #731. It specifies executable staged RED precursors for service, outbox delivery, and preservation status; these tasks preserve all previously approved criteria.

All test fixtures and sentinel content must be synthetic. No task reads or copies real transcript content. No task performs live recovery. The first operational pilot remains separately gated on explicit Fer authorization after implementation, QA and security review.

## Summary and actual dependency graph

| Order | Tasks | Scope | Required dependencies |
|---|---|---|---|
| 1 | T-1 → T-2 | durable recovery/outbox/claim/pilot persistence | RED test before migration/model implementation |
| 2 | T-3 → T-4 | existing-app disabled-mode route precursor | T-2 for GREEN persistence boundary; route RED before safe fail-closed GREEN |
| 3 | T-17 → T-18 | complete guarded service operation | T-4, T-2 and T-6; behavioral RED through existing route before full service GREEN |
| 4 | T-5 → T-6 | shared durable worker fencing | T-2; worker RED before worker GREEN |
| 5 | T-7 → T-8 | worker-startup delivery of committed outbox rows | T-18, T-2 and T-6; existing startup RED before dispatcher wiring |
| 6 | T-19 → T-20 | ambiguous-ack retry and deduplication | T-8 and T-18; behavioral RED against existing dispatcher before retry GREEN |
| 7 | T-9 → T-10 | fail-closed status for empty artifact sets | T-18; existing-app status RED before safe status GREEN |
| 8 | T-21 → T-22 | complete nonempty all-field snapshot | T-10 and T-2; behavioral RED through existing status route before full snapshot GREEN |
| 9 | T-11 → T-12 | explicit authenticated API, privacy and no-auto-trigger boundary | T-18, T-20, T-22 and T-6; full API RED before complete API GREEN |
| 10 | T-13 → T-14 | one-meeting pilot lock and operator verification | T-12 and T-22; pilot RED before gate GREEN |
| 11 | T-15 → T-16 | end-to-end synthetic recovery regression | T-6, T-20, T-22, T-14; integration RED before final verification GREEN |

RED tasks must demonstrate the specified behavioral failure at the relevant stage and retain its exact output in issue/PR evidence. For staged boundaries, the first RED targets an existing app/startup boundary; its safe GREEN adds only the narrow fail-closed behavior, then a subsequent RED targets that now-existing boundary before its full GREEN. No RED may pass only because a module/callable is absent; no GREEN may accept recovery before eligibility, fencing, pilot, and content-safety prerequisites exist. Each GREEN task makes its paired tests pass. Listed prerequisites are the only DAG edges; tasks within separate branches may proceed in parallel when dependencies are met. The commands below run from `backend/` in the project worktree: `python -m pytest <listed test path> -q` (backend's configured pytest command; no live services unless a test explicitly uses the project's existing isolated integration fixture).

## T-1 — RED: Specify durable recovery persistence constraints

**Files / RED test seams:** `backend/tests/infra/test_manual_recovery_persistence.py` (new), exercising the existing Alembic helpers `backend/tests/test_migration.py:_migration_script()` and `backend/tests/test_migration.py:_run_migration(engine, migration, direction)`; use `test_speaker_review_receipt_migration_preserves_persisted_contract` as the existing isolated upgrade-test pattern.

**Action:** Add failing synthetic DB/schema tests for a recovery-operation row, one outbox row uniquely bound to an operation, durable per-meeting generation/claim, and a singleton pilot-gate row. Assert unique idempotency scope, unique outbox operation, required foreign keys, and that recovery/audit rows have no fields for transcript text, notes, raw broker payloads, or media references. Test rollback/history-retention constraints from the design without deleting existing meeting artifacts.

**Done evidence / validation:** RED run shows the expected missing-model/schema assertions, not import/setup errors: `python -m pytest tests/infra/test_manual_recovery_persistence.py -q`.

**Dependencies:** None.

## T-2 — GREEN: Add minimum durable recovery schema

**Files:** `backend/app/infra/models.py`; next sequential `backend/alembic/versions/` migration; `backend/tests/infra/test_manual_recovery_persistence.py`.

**Action:** Implement the smallest ORM/migration structures matching the approved conceptual records: processing control/generation, recovery operation with scoped idempotency, outbox, and singleton pilot gate. Follow current SQLAlchemy/Alembic conventions, use synthetic/opaque identifiers, and avoid storing content or raw payloads. Migration and ORM changes ship together; do not remove or overwrite existing meeting/artifact data.

**Done evidence / validation:** T-1 passes against the migrated isolated test DB and migration upgrade/downgrade checks demonstrate the documented rollback boundary: `python -m pytest tests/infra/test_manual_recovery_persistence.py -q`.

**Dependencies:** T-1.

## T-3 — RED: Specify the safe disabled-mode recovery route precursor

**Files / RED test seams:** `backend/tests/meetings/test_manual_recovery_routes.py` (new); existing FastAPI app test client invoking `POST /api/v1/meetings/{meeting_id}/recover` with an authenticated owner-scoped synthetic meeting; existing app factory/route registration seam as used by the repository's API tests.

**Action:** Before adding production recovery code, assert that disabled mode returns the specified content-free disabled/no-op result and leaves meeting, operation, outbox, and queue state unchanged. Assert a non-owner receives the existing not-found behavior without state disclosure. The current route returns HTTP 404, so the expected RED is the route status/result assertion, not a missing-module import. Use synthetic records only.

**Done evidence / validation:** Capture the expected HTTP result/assertion failure (not fixture/setup failure): `python -m pytest tests/meetings/test_manual_recovery_routes.py -q`.

**Dependencies:** None.

## T-4 — GREEN: Add only the fail-closed disabled-mode route/service boundary

**Files:** `backend/app/meetings/router.py` (`POST /api/v1/meetings/{meeting_id}/recover`); `backend/app/meetings/recovery_service.py` (new, initial safe boundary); existing owner authorization dependencies; `backend/tests/meetings/test_manual_recovery_routes.py`.

**Action:** Add the authenticated owner-scoped route and service boundary that returns a content-free disabled/no-op result without meeting, recovery, outbox, or queue mutation. Preserve not-found behavior for unauthorized/non-owner callers. Do not accept or dispatch a recovery while eligibility and shared worker fencing are not implemented; this precursor must remain fail-closed and cannot be a production stub that reports success.

**Done evidence / validation:** T-3 disabled-mode and authorization assertions pass; state comparisons prove no writes: `python -m pytest tests/meetings/test_manual_recovery_routes.py -q`.

**Dependencies:** T-3 and T-2.

## T-17 — RED: Specify complete guarded service behavior through the existing route

**Files / RED test seams:** `backend/tests/meetings/test_recovery_service.py` (new), invoking the now-existing FastAPI `POST /api/v1/meetings/{meeting_id}/recover` and the real `backend/app/meetings/recovery_service.py:MeetingRecoveryService.recover(meeting_id, actor_id, idempotency_key)` through its route/service boundary.

**Action:** With a seeded synthetic pilot-mode setting/gate and an eligible synthetic owner-scoped meeting, assert exactly one fenced, idempotent operation/outbox row using only the persisted recording, with the gate atomically claimed for that same meeting. Add assertion-based no-op/no-write cases for missing/mismatched gate, wrong state, missing/duplicate recording, generated artifacts, uncertain probes, active/pending work, and DB/query/transaction errors; check isolation, notes/speakers/retention preservation, and same-key deduplication. T-4 refuses acceptance, so RED must fail on observable result/state assertions, not import errors or `hasattr`; no live pilot is authorized.

**Done evidence / validation:** Expected behavioral result/state assertion failures: `python -m pytest tests/meetings/test_recovery_service.py -q`.

**Dependencies:** T-4, T-2, and T-6.

## T-18 — GREEN: Implement guarded meeting recovery service

**Files:** `backend/app/meetings/recovery_service.py`; `backend/app/meetings/state_machine.py` only if the existing event vocabulary lacks the specifically named recovery transition; the minimal required repository/service modules; `backend/tests/meetings/test_recovery_service.py`.

**Action:** Implement `MeetingRecoveryService.recover(...)` to acquire the durable meeting fence before mutable eligibility reads; require a configured pilot mode and exact unused singleton-gate match; fail closed without recovery mutations on any false/unknown condition; and atomically claim the gate with operation/outbox on eligibility. Revalidate state/generation in-transaction and use only the persisted recording. Record the approved return to transcription-ready `transcribing` state via existing history semantics. Never replay ingestion, delete/reset outputs, or add automatic request retries.

**Done evidence / validation:** T-17 behavioral assertions pass; every ineligible case leaves meeting, recording, artifacts, queue, and operation state unchanged: `python -m pytest tests/meetings/test_recovery_service.py -q`.

**Dependencies:** T-17, T-2, and T-6.

## T-5 — RED: Specify durable worker claim and generation fencing

**Files:** `backend/tests/transcription/test_recovery_worker_fence.py` and `backend/tests/diarization/test_recovery_worker_fence.py` (new); seams `app.transcription.worker._process_transcription` and `app.diarization.worker._process_diarization`.

**Action:** Add failing synthetic interleaving tests for worker-claim-first and recovery-claim-first, stale/missing/mismatched generation, delayed legacy delivery, duplicate delivery, expired/uncertain claim, and worker restart. Assert a rejected job invokes no engine and causes no state/artifact write; a valid claim permits only one side-effecting execution for its generation.

**Done evidence / validation:** Expected fence failures (not setup/import failures) from both modules: `python -m pytest tests/transcription/test_recovery_worker_fence.py tests/diarization/test_recovery_worker_fence.py -q`.

**Dependencies:** T-2.

## T-6 — GREEN: Fence transcription and diarization workers

**Files:** `backend/app/transcription/worker.py`; `backend/app/diarization/worker.py`; normal job producers in the corresponding existing modules; paired worker tests.

**Action:** Make both workers and their normal producers participate in the shared durable claim/generation protocol. Validate job, meeting, recording and owner binding before transition, engine call or artifact write; reject legacy jobs lacking verifiable generation for recovery-sensitive meetings; safely acknowledge stale/duplicate deliveries. Preserve existing normal processing behavior outside recovery and never infer idleness from broker counts or lease expiry alone.

**Done evidence / validation:** All T-5 interleavings pass, with engine-call and DB-write assertions: `python -m pytest tests/transcription/test_recovery_worker_fence.py tests/diarization/test_recovery_worker_fence.py -q`.

**Dependencies:** T-5 and T-2.

## T-7 — RED: Specify recovery outbox delivery at worker startup

**Files / RED test seams:** `backend/tests/infra/test_recovery_outbox.py` (new); existing `backend/app/worker/main.py` startup boundary with injected isolated queue/session factories and controlled stop event; use a persisted synthetic operation/outbox row produced through `MeetingRecoveryService.recover`.

**Action:** After T-18 can create an authorized synthetic operation/outbox row, run the existing worker startup boundary and assert it publishes that committed row's opaque operation/generation once logically and does not create another operation. Before dispatcher wiring, fail on publish/row-state behavior, not imports. Assert ordinary startup with no authorized recovery row publishes no recovery message and that transaction rollback leaves no publishable outbox row.

**Done evidence / validation:** Expected startup publish/state assertion failures: `python -m pytest tests/infra/test_recovery_outbox.py -q`.

**Dependencies:** T-18, T-2, and T-6.

## T-8 — GREEN: Wire startup to deliver only committed outbox records

**Files:** `backend/app/infra/recovery_outbox.py` (new); `backend/app/worker/main.py` existing startup boundary; `backend/app/infra/queue.py:JobQueue.publish`; `backend/app/infra/queue_rabbitmq.py:RabbitMQJobQueue.publish`; `backend/tests/infra/test_recovery_outbox.py`.

**Action:** Implement the minimum `dispatch_pending_recoveries(...)` path and wire worker startup only to delivery of already-accepted committed outbox rows using stable operation/generation identifiers. It must never initiate recovery or alter meeting processing state; ordinary startup without an authorized row does not publish recovery. Narrow touched logs to content-free reason codes/opaque IDs. Do not claim ambiguous delivery retry safety yet; T-19/T-20 provide its required RED→GREEN pair.

**Done evidence / validation:** T-7 startup and rollback assertions pass: `python -m pytest tests/infra/test_recovery_outbox.py -q`.

**Dependencies:** T-7, T-2, T-18, and T-6.

## T-19 — RED: Specify stable outbox retry after ambiguous acknowledgement

**Files / RED test seams:** `backend/tests/infra/test_recovery_outbox.py`; existing `backend/app/infra/recovery_outbox.py:dispatch_pending_recoveries` and `backend/app/infra/queue_rabbitmq.py:RabbitMQJobQueue.publish`.

**Action:** Inject a synthetic publish/ack ambiguity and assert retry reuses the same operation ID and generation, does not create a second operation or logical job, retains dispatch-pending state until publish semantics permit completion, and excludes transcript/note/participant/object-reference sentinels from payload/log captures. The dispatcher now exists, so failures must be behavioral assertions.

**Done evidence / validation:** Expected retry/idempotency/content assertion failures: `python -m pytest tests/infra/test_recovery_outbox.py -q`.

**Dependencies:** T-8 and T-18.

## T-20 — GREEN: Complete durable outbox retry and deduplication

**Files:** `backend/app/infra/recovery_outbox.py:dispatch_pending_recoveries`; `backend/app/infra/queue_rabbitmq.py:RabbitMQJobQueue.publish`; `backend/tests/infra/test_recovery_outbox.py`.

**Action:** Complete the committed-operation retry path for ambiguous publish acknowledgement using stable operation/generation identity, with no second recovery operation or logical job. Preserve content-free payload/logging and the state semantics required by the approved design.

**Done evidence / validation:** T-19 retry, idempotency, state and content-exclusion assertions pass: `python -m pytest tests/infra/test_recovery_outbox.py -q`.

**Dependencies:** T-19 and T-8.

## T-9 — RED: Specify fail-closed status for an empty-artifact recovery

**Files / RED test seams:** `backend/tests/meetings/test_recovery_preservation.py` (new); existing FastAPI app test client invoking owner-scoped `GET /api/v1/meetings/{meeting_id}/recoveries/{operation_id}` for a synthetic completed recovery with no note or confirmed-speaker/assignment rows.

**Action:** Before a status route exists, assert the response explicitly reports `preservation_verified=false` whenever preservation cannot yet be established and never includes content or a digest. The current app returns 404; the expected RED is the HTTP status/result assertion, not a missing helper import. Test owner authorization and no disclosure on a mismatched meeting/operation pair.

**Done evidence / validation:** Expected status-route HTTP assertion failure: `python -m pytest tests/meetings/test_recovery_preservation.py -q`.

**Dependencies:** T-18.

## T-10 — GREEN: Add fail-closed status for empty artifact sets

**Files:** `backend/app/meetings/router.py` (owner-only recovery status GET); the minimum status service/persistence boundary; `backend/tests/meetings/test_recovery_preservation.py`.

**Action:** Add the real owner-authorized status route with composite meeting/operation lookup and no disclosure on mismatch. For recovery operations whose preserved artifact sets contain no note or confirmed-speaker/assignment rows, compute and persist/compare a real empty-set snapshot and counts, returning verified only when the complete check succeeds. Any nonempty or unreadable set returns `preservation_verified=false` and cannot advance the pilot gate. This is a limited safe behavior, not an always-false placeholder; do not expose or log digests.

**Done evidence / validation:** T-9 status, authorization, mismatch, empty-set and content-free assertions pass: `python -m pytest tests/meetings/test_recovery_preservation.py -q`.

**Dependencies:** T-9 and T-2.

## T-21 — RED: Specify nonempty all-field preservation behavior

**Files / RED test seams:** `backend/tests/meetings/test_recovery_preservation.py`; now-existing `GET /api/v1/meetings/{meeting_id}/recoveries/{operation_id}` route and its real status/snapshot service boundary. Use persisted synthetic note and confirmed-speaker/assignment rows with content sentinels.

**Action:** Assert unchanged nonempty rows verify true; in-place change to any persisted field with unchanged row IDs, added/deleted rows, nondeterministic row ordering, or read failure returns `preservation_verified=false`; responses/logs never contain sentinel content or digest. T-10 deliberately remains fail-closed for nonempty sets, so the unchanged-row assertion must fail behaviorally at the status verdict, not during import or route lookup.

**Done evidence / validation:** Expected behavioral preservation assertion failures: `python -m pytest tests/meetings/test_recovery_preservation.py -q`.

**Dependencies:** T-10 and T-2.

## T-22 — GREEN: Implement complete all-field preservation snapshot

**Files:** the existing status/snapshot service boundary under `backend/app/meetings/`; recovery persistence fields from T-2; `backend/tests/meetings/test_recovery_preservation.py`.

**Action:** Extend the snapshot to deterministic type-tagged canonical serialization of every persisted field for each preserved note and confirmed-speaker/assignment row, sorted by row type and ID. Persist only digest and counts, recompute on status reads, report false on mismatch/read failure, and never expose/log digest, serialized values, or artifact content.

**Done evidence / validation:** All T-21 unchanged/edit/insert/delete/read-failure and content-exclusion assertions pass: `python -m pytest tests/meetings/test_recovery_preservation.py -q`.

**Dependencies:** T-21 and T-10.

## T-11 — RED: Specify authenticated manual recovery API boundary

**Files:** `backend/tests/meetings/test_manual_recovery_routes.py` (new); route seam `backend/app/meetings/router.py` and existing `_get_authorized_meeting`/`get_current_user` authorization dependencies.

**Action:** Add failing synthetic API tests for explicit single-meeting `POST /api/v1/meetings/{meeting_id}/recover`, mandatory bounded `Idempotency-Key`, owner-only access and existing not-found disclosure behavior, no client-supplied owner/object/state/batch fields, finite content-free result/reason, and no transcript/note/speaker/media sentinels in response, audit, log or persisted recovery rows. Assert normal `process_ingestion` keeps its service-level `is_new=False` and persisted-state behavior for existing recordings, and that ordinary ingestion/startup paths do not call recovery; do not treat that service test as route/publisher evidence.

**Done evidence / validation:** Expected missing-route/guard assertions fail without environment/setup errors: `python -m pytest tests/meetings/test_manual_recovery_routes.py tests/ingestion/test_idempotency_property.py -q`.

**Dependencies:** T-18, T-20, T-22, and T-6.

## T-12 — GREEN: Add explicit owner-authenticated recovery route

**Files:** `backend/app/meetings/router.py` (route function `recover_meeting_endpoint`, `POST /api/v1/meetings/{meeting_id}/recover`); route schemas in `backend/app/meetings/schemas.py` if needed; `backend/tests/meetings/test_manual_recovery_routes.py`.

**Action:** Add only the designed authenticated explicit recovery POST, reuse existing current-user, meeting-owner authorization and access-audit mechanisms, require `Idempotency-Key`, and delegate to `MeetingRecoveryService.recover`. Return only operation/reference, finite status/reason and timestamps. Do not wire recovery to ingestion, worker startup, scheduler, or normal retries; preserve existing not-found semantics. Do not add a frontend/client or shared-types change.

**Done evidence / validation:** T-11 endpoint, authorization, privacy and ordinary-flow regression assertions pass: `python -m pytest tests/meetings/test_manual_recovery_routes.py tests/ingestion/test_idempotency_property.py -q`.

**Dependencies:** T-11, T-18, T-20, T-22, and T-6.

## T-13 — RED: Specify single-pilot gate and operator verification

**Files / RED test seams:** `backend/tests/meetings/test_recovery_pilot_gate.py` (new); route functions in `backend/app/meetings/router.py`: `get_recovery_status_endpoint` for `GET /api/v1/meetings/{meeting_id}/recoveries/{operation_id}` and `verify_recovery_pilot_endpoint` for `POST /api/v1/meetings/{meeting_id}/recoveries/{operation_id}/verify-pilot`.

**Action:** Add failing tests for disabled mode, missing/mismatched allowlist, first exact-meeting operation atomically claiming the singleton gate, competing/second meeting no-op, status authorization/path+operation composite binding with indistinguishable not-found mismatch, incomplete processing, changed/unreadable preservation snapshot, named pilot-operator-only explicit verification, successful one-time verification and permanently blocked second meeting. Assert all responses remain content-free.

**Done evidence / validation:** Expected pilot/status/verification assertions fail: `python -m pytest tests/meetings/test_recovery_pilot_gate.py -q`.

**Dependencies:** T-12 and T-22.

## T-14 — GREEN: Implement pilot status and verification gate

**Files:** `backend/app/meetings/router.py` (route functions `get_recovery_status_endpoint` and `verify_recovery_pilot_endpoint`); `backend/app/meetings/recovery_service.py` or narrow pilot-gate service; runtime configuration at existing settings boundary; `backend/tests/meetings/test_recovery_pilot_gate.py`.

**Action:** Implement fail-closed mode `disabled` by default and the approved one-ID `pilot` gate. Bind status/verification lookups to both path meeting and operation ID and require gate allowlist match; return the same not-found behavior on mismatch. Status returns only processing state, reason, timestamps, final meeting state and preservation verdict. Permit the named pilot operator's explicit `verified=true` acknowledgement only after completed work and exact snapshot match; atomically move to verified. Do not re-arm, expand, batch, trigger, deploy, or authorize another meeting.

**Done evidence / validation:** T-13 gate transitions, access isolation, fail-closed and no-second-meeting tests pass: `python -m pytest tests/meetings/test_recovery_pilot_gate.py -q`.

**Dependencies:** T-13, T-12, and T-22.

## T-15 — RED: Specify complete synthetic recovery boundary and ordinary-flow invariance

**Files / RED test seams:** `backend/tests/integration/test_manual_recovery_pipeline.py` (new); `backend/app/meetings/router.py:recover_meeting_endpoint` (`POST /api/v1/meetings/{meeting_id}/recover`), `get_recovery_status_endpoint` (`GET /api/v1/meetings/{meeting_id}/recoveries/{operation_id}`), and `verify_recovery_pilot_endpoint` (`POST /api/v1/meetings/{meeting_id}/recoveries/{operation_id}/verify-pilot`); `backend/app/meetings/recovery_service.py:MeetingRecoveryService.recover`; `backend/app/infra/recovery_outbox.py:dispatch_pending_recoveries`; `backend/app/infra/queue_rabbitmq.py:RabbitMQJobQueue.publish`; `backend/app/transcription/worker.py:_process_transcription`; `backend/app/diarization/worker.py:_process_diarization`.

**Action:** Add failing synthetic integration tests that exercise the named route functions and HTTP paths across persisted recording → committed operation/outbox → `dispatch_pending_recoveries`/`RabbitMQJobQueue.publish` → fenced `_process_transcription` result → status/pilot-verification route responses and preservation verdict. Also cover representative ineligible no-op, queue rollback/dispatch-pending behavior, unchanged existing-recording ingestion, and absence of automatic recovery during ingestion/worker startup/normal jobs. Use isolated synthetic DB/broker fixtures; never operate on live meetings.

**Done evidence / validation:** Expected end-to-end recovery contract failures (not test-environment setup failures): `python -m pytest tests/integration/test_manual_recovery_pipeline.py -q`.

**Dependencies:** T-6, T-20, T-22, and T-14.

## T-16 — GREEN: Verify integrated guarded recovery without widening triggers

**Files:** only the minimal integration wiring in existing approved backend boundaries and `backend/tests/integration/test_manual_recovery_pipeline.py`.

**Action:** Complete the integration among the already implemented route/service/outbox/fenced workers/status gate, correcting only missing approved interfaces. Keep recovery reachable only through explicit authenticated human request and disabled by default. Preserve ordinary ingestion, normal worker startup/retries, notes, speakers, retention and consent behavior. Do not perform or authorize the live one-meeting pilot.

**Done evidence / validation:** T-15 passes; run the focused recovery and ingestion regression sets: `python -m pytest tests/integration/test_manual_recovery_pipeline.py tests/meetings/test_recovery_service.py tests/meetings/test_manual_recovery_routes.py tests/meetings/test_recovery_pilot_gate.py tests/meetings/test_recovery_preservation.py tests/infra/test_manual_recovery_persistence.py tests/infra/test_recovery_outbox.py tests/transcription/test_recovery_worker_fence.py tests/diarization/test_recovery_worker_fence.py tests/ingestion/test_idempotency_property.py -q`.

**Dependencies:** T-15, T-6, T-20, T-22, and T-14.

## Constraints and deferred gate

- Validation tasks use only synthetic data. The cited existing QA reproduction at `app.ingestion.service.process_ingestion` covers only that service return/persisted state; it is not proof of API routing, queue publication or live worker idleness.
- The transcript-bearing observed candidate stays intact and requires review. No candidate ID/time is an eligibility criterion. Uncertain active work or any generated output means no-op.
- Operational use remains a separate post-implementation gate: implementation, QA, security review, and explicit Fer authorization must occur before the operator configures the protected one-meeting pilot. This plan authorizes none of those live actions.
