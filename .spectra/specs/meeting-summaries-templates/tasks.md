# Implementation Plan — Meeting Summaries and Templates

**Spec:** `meeting-summaries-templates`
**Approved inputs:** requirements `cdce9c34c566b72f42bb6db5eecdd76bdacb4532` (Mira APPROVED, PR #231 merged); owner-approved `PRODUCT_BASELINE.md` `26d44ca7b212097c82415d0ae038bd9d096873d4` (blob `3afefd5e3da230cc3e26d7b89e74f48dc01d82ae`); design `23e7ed13546ea2abdfc58da87e0f7208b3da94e9` (Mira APPROVED, PR #268 open). These identify planning sources; they are not recurring implementation checks.

## Planning constraints and unresolved gates

- Follow the approved requirements and design only. No provider, model, endpoint, credential, template grammar, summary serialization, seed template, no-default fallback, or broader retention behavior is selected here.
- Design D14 requires a verified `SummarizationEngine` provider/configuration/deployment binding before work whose acceptance depends on actual summary generation. Resolve that binding through the authorized decision process before dispatching those gated tasks; obtain upstream approval if the choice affects privacy, cost, or product behavior. Protocol/repository/resolver/API/UI-empty-state/outbox work that does not require generation is independent and may proceed.
- Behavior when neither an explicit template nor a personal default exists remains unspecified. Do not infer a fallback or add acceptance tests for one.
- Tests use synthetic fixtures only. Backend property tests use the already-present `hypothesis` dependency and run at least 100 examples per property. Test tasks are RED: commit the test and record the pre-implementation candidate SHA, exact command, captured failing output, and expected failure before their dependent implementation task starts. Hand the test commit/diff and evidence to that implementation task. Candidate work must include the predecessor test commit. No late test substitutes for RED evidence.
- Suggested ready-task execution remains parallel across independent dependency branches; separate worktrees are required. Phase headings group work and do not add dependencies.

## Resumen de Fases

| Fase | Descripción | Tareas | Dependencias |
|---|---|---|---|
| 1 | Persistence foundations and default resolution | T1–T4 | RED→GREEN within each branch |
| 2 | Personal templates and privacy boundaries | T5–T8 | T2/T4 where noted; otherwise independent |
| 3 | Summary request, outbox, worker and API | T9–T16 | Explicit DAG below; generation tasks additionally gated by D14 |
| 4 | Shared contracts and web experiences | T17–T24 | Backend/API contracts where noted |
| 5 | End-to-end integration and validation | T25–T27 | Required predecessor tasks |

## Fase 1: Persistence Foundations and Default Resolution

### T1: RED — Assert no seed template/default and required persistence relationships

**Tracking:** Issue #269 · Card task_9240ba5b9f47485a

**Archivo:** `backend/tests/summaries/test_summary_models_property.py` (create)
**Acción:** Add synthetic-database/property coverage for the approved absence of a seeded template or configured default (P4), multiple summary generations per transcript, unique event/generation constraints, and deletion of every persisted summary when its transcript is deleted (P8/R6). Do not test a broader retention policy. Capture the pre-implementation candidate SHA and expected failing output.

**Criterio de Completado:** Before schema implementation, `cd backend && pytest tests/summaries/test_summary_models_property.py -q` fails on the missing schema/relationship assertions; commit the RED test and record exact SHA and output.

**Dependencias:** Ninguna

### T2: GREEN — Add summary/template persistence models and migration

**Tracking:** Issue #270 · Card task_76551eb8a88047d8

**Archivo:** `backend/app/infra/models.py`; `backend/alembic/versions/008_summaries_and_templates.py`
**Acción:** Implement the design's `TemplateCategory`, `SummaryTemplate`, `SummaryRequestOutbox`, `ProcessedSummaryEvent`, and `MeetingSummary` models, nullable `User.default_summary_template_id`, constraints and FKs; add migration `008` from `007_rename_schema_to_english` in the specified create/reverse order. Do not seed templates/defaults. Use transcript `ON DELETE CASCADE`, user-default `ON DELETE SET NULL`, and allow multiple summary generations.

**Criterio de Completado:** T1's RED test passes and `cd backend && pytest tests/summaries/test_summary_models_property.py -q` succeeds; migration upgrade/downgrade is exercised by the repository's configured test fixture.

**Dependencias:** T1 (mandatory RED→GREEN)

### T3: RED — Specify personal default resolver invariants (P3)

**Tracking:** Issue #271 · Card task_7b7ebdd955cd446a

**Archivo:** `backend/tests/templates/test_default_resolver_property.py` (create)
**Acción:** Add Hypothesis properties for nullable default resolution, exact `(template_id, version)` selection, and the resolver's category-blind input/output contract; use at least 100 examples per property and synthetic template records. Do not assert any no-default fallback.

**Criterio de Completado:** Before resolver implementation, `cd backend && pytest tests/templates/test_default_resolver_property.py -q` fails because the resolver is absent; commit RED test and record SHA/output.

**Dependencias:** Ninguna

### T4: GREEN — Implement personal default resolver

**Tracking:** Issue #272 · Card task_c395d0ef59904831

**Archivo:** `backend/app/templates/default_resolver.py`
**Acción:** Implement the pure `ResolvedDefault`/`resolve_default(template_row)` contract in the approved design, returning `None` for no row and the exact id/version otherwise; do not inspect category or infer fallback behavior.

**Criterio de Completado:** T3's RED test passes with at least 100 examples per property: `cd backend && pytest tests/templates/test_default_resolver_property.py -q`.

**Dependencias:** T3 (mandatory RED→GREEN)

## Fase 2: Personal Templates and Privacy Boundaries

### T5: RED — Specify personal template API ownership and category rules (P7)

**Tracking:** Issue #273 · Card task_e09b78921ec548f0

**Archivo:** `backend/tests/templates/test_templates_api.py` (create/extend)
**Acción:** Add tests for own-template CRUD/listing, multiple templates, optional category assignment (including multiple templates per category), cross-owner edit/read denial, and ensuring API responses expose only the requesting user's templates. Cover `GET /api/v1/templates/categories` returning only the caller's categories, `POST /api/v1/templates/categories` creating a caller-owned category, rejection (422) when a template references a foreign category, and no unauthorized mutation or category disclosure. Include the literal category route ordering guard required by the design. Use synthetic users/templates/categories.

**Criterio de Completado:** Before API implementation, `cd backend && pytest tests/templates/test_templates_api.py -q` fails on missing template/category routes or behavior, including own-category list/create and foreign-category isolation; commit RED test and record SHA/output.

**Dependencias:** T2 (models required for fixture/schema tests)

### T6: GREEN — Implement personal template/category CRUD API

**Tracking:** Issue #274 · Card task_67c8568db9084220

**Archivo:** `backend/app/templates/router.py`; `backend/app/templates/service.py`; `backend/app/templates/repository.py`; `backend/app/templates/schemas.py`; `backend/app/main.py`
**Acción:** Implement the designed authenticated templates module and route registration, including `GET /api/v1/templates/categories` (list only caller-owned categories) and `POST /api/v1/templates/categories` (create a caller-owned category). Register the static `/categories` routes before `/{template_id}`. Restrict template/category list/read/update operations to caller-owned records; validate category ownership; transport `instructions` as an unchanged opaque string; support optional category, multiple templates per category, and the specified 404/422 semantics. Do not add template deletion, schema/grammar validation, or cross-user sharing.

**Criterio de Completado:** T5's RED test passes: `cd backend && pytest tests/templates/test_templates_api.py -q`.

**Dependencias:** T5 (mandatory RED→GREEN), T2

### T7: RED — Specify default setting and category-independent identification (P3/P7)

**Tracking:** Issue #275 · Card task_fdefb390888b442b

**Archivo:** `backend/tests/templates/test_templates_api.py` (extend)
**Acción:** Add tests that a user can set their own template as the one personal default, a foreign template cannot be selected, template-list responses identify the caller's configured default, and the default is independent of category. Verify failed foreign selection makes no change. Do not assert no-default request behavior.

**Criterio de Completado:** Before default API implementation, `cd backend && pytest tests/templates/test_templates_api.py -q` fails on default-setting/list-identification cases; commit RED test and record SHA/output.

**Dependencias:** T6 (reuse template API fixture and owner boundary)

### T8: GREEN — Implement personal default endpoint and template-list default marker

**Tracking:** Issue #276 · Card task_1ed8f8fddd504946

**Archivo:** `backend/app/templates/router.py`; `backend/app/templates/service.py`; `backend/app/templates/repository.py`; `backend/app/templates/schemas.py`
**Acción:** Implement `PUT /api/v1/templates/default` with ownership validation and the designed 204 response, and include the requesting user's `isDefault` marker in template-list output. Ensure one nullable user reference is the only default and category does not participate in resolution.

**Criterio de Completado:** T7's RED cases pass: `cd backend && pytest tests/templates/test_templates_api.py -q`.

**Dependencias:** T7 (mandatory RED→GREEN), T4, T6

## Fase 3: Summary Request, Outbox, Worker and API

### T9: RED — Specify accepted-request snapshot, generations, status and outbox recovery (P8)

**Tracking:** Issue #277 · Card task_be32b6373a0648dc

**Archivo:** `backend/tests/summaries/test_summary_api.py`; `backend/tests/integration/test_summary_pipeline.py` (create/extend)
**Acción:** Add failing tests for explicit owned-template selection and implicit configured-default resolution at request time; each accepted event freezes template id/version/instructions, distinct requests receive increasing per-transcript generations, no enqueue occurs on transcript commit alone, and committed pending outbox events survive/re-dispatch after publication failure until broker confirmation. Cover status lifecycle and do not invent behavior when no default exists.

**Criterio de Completado:** Before request/outbox implementation, `cd backend && pytest tests/summaries/test_summary_api.py tests/integration/test_summary_pipeline.py -q` fails with missing API/outbox behavior; commit RED tests with pre-implementation SHA and captured output.

**Dependencias:** T2, T8

### T10: GREEN — Implement summary request acceptance and durable outbox dispatch

**Tracking:** Issue #278 · Card task_dd486ec8afa04e97

**Archivo:** `backend/app/summaries/router.py`; `backend/app/summaries/service.py`; `backend/app/summaries/repository.py`; `backend/app/summaries/outbox.py`; `backend/app/infra/queue_rabbitmq.py`
**Acción:** Accept a summary request only for an available transcript; validate explicit template ownership or resolve the configured personal default; atomically persist a unique increasing-generation request and immutable template id/version/instructions snapshot. Implement a recoverable dispatcher that republishes pending events after restart/failure and marks them delivered only after broker confirmation. Do not enqueue from transcript commit; preserve no-default as unresolved/gated.

**Criterio de Completado:** T9's RED cases pass using `cd backend && pytest tests/summaries/test_summary_api.py tests/integration/test_summary_pipeline.py -q`; duplicate publication remains safe to consume in T12.

**Dependencias:** T9 (mandatory RED→GREEN), T2, T8

### T11: RED — Specify summary worker idempotency and atomic outcome transitions (P8)

**Tracking:** Issue #279 · Card task_4fb964f1c8d54d70

**Archivo:** `backend/tests/summaries/test_worker.py` (create/extend)
**Acción:** Add failing tests for immutable event-snapshot use across template edits/default changes, duplicate-event no-op, atomic summary + processed-event + `succeeded` persistence, retryable failures, terminal dead-letter `failed`, and status transitions `pending → running → succeeded|failed`. Assert a later failed request does not overwrite an earlier successful summary.

**Criterio de Completado:** Before worker implementation, `cd backend && pytest tests/summaries/test_worker.py -q` fails on the missing consumer behavior; commit RED test and record SHA/output.

**Dependencias:** T2, T9

### T12: GREEN — Implement summary event worker and event idempotency

**Tracking:** Issue #280 · Card task_d05f492a1c11477f

**Archivo:** `backend/app/summaries/worker.py`; `backend/app/summaries/repository.py`; `backend/app/worker.py`
**Acción:** Consume accepted outbox events using only the frozen template snapshot; atomically persist a successful structured summary, processed-event claim and request status. Make already-committed `event_id` deliveries a no-op; let generation errors propagate for queue retries, and mark terminal dead-letter requests failed without exposing provider exception details. Register in the existing worker process; do not trigger it on transcript commit.

**Criterio de Completado:** T11's RED test passes: `cd backend && pytest tests/summaries/test_worker.py -q`.

**Dependencias:** T11 (mandatory RED→GREEN), T10

### T13: RED — Specify required generated content and lineage (P1)

**Tracking:** Issue #281 · Card task_5af1bb7ec0114ea4

**Archivo:** `backend/tests/summaries/test_worker.py`; `backend/tests/integration/test_summary_pipeline.py` (extend)
**Acción:** Add failing integration tests asserting that every successful persisted result makes both topic and key points identifiable, reflects the applied template instructions through the engine boundary, records template id/version lineage, and is unaffected by later template edits. Add factory contract tests that unsupported/missing provider configuration fails closed. Use synthetic transcript text and a contract-compliant test engine; do not assert provider accuracy, a prompt, or output policy for empty values.

**Criterio de Completado:** Before generation integration, `cd backend && pytest tests/summaries/test_worker.py tests/integration/test_summary_pipeline.py -q` fails on missing engine/content assertions; commit RED test and capture exact output. Actual-provider acceptance remains gated by D14.

**Dependencias:** T10, T12

### T14: GREEN — Add engine protocol and fail-closed provider/configuration seam

**Tracking:** Issue #282 · Card task_ae51c57ca7ed46e4

**Archivo:** `backend/app/summaries/engine.py`; `backend/app/summaries/factory.py`; `backend/app/summaries/worker.py`
**Acción:** Implement the `SummarizationEngine` protocol and factory seam; validate unsupported/missing configuration fail-closed at worker startup and keep business services provider-agnostic. Do not select or claim an actual provider, endpoint, model, credential, or executable generation deployment. The D14 provider/configuration/deployment binding and its adapter remain a separate gated prerequisite before any provider-backed summary-generation acceptance; if it changes privacy, cost, or product behavior, obtain upstream approval. Once authorized, the adapter must use bounded TLS-protected requests containing only transcript text needed for topic/key-points, not recording media, identity, template names or unrelated metadata.

**Criterio de Completado:** T13's contract-engine and fail-closed configuration RED tests pass with `cd backend && pytest tests/summaries/test_worker.py tests/integration/test_summary_pipeline.py -q`. This does not establish a production provider or prove provider-backed generation; those remain blocked until the D14 binding is verified.

**Dependencias:** T13 (mandatory RED→GREEN), T12; provider-backed portion is gated by the D14 binding

### T15: RED — Specify current successful summary query and status routes (P5/P8)

**Tracking:** Issue #283 · Card task_abb0a6217a484a7a

**Archivo:** `backend/tests/summaries/test_summary_api.py` (extend)
**Acción:** Add failing tests for GET current summary choosing the highest-generation successful result (not a pending/failed later request), meeting association/ownership and `require_sales` access behavior, latest accepted request status selection, event-specific status ownership, and registration of static `/summary-requests/latest` before dynamic `{event_id}`. Include the literal-route test named `test_latest_summary_request_route_resolves_before_event_id`.

**Criterio de Completado:** Before read/status route implementation, `cd backend && pytest tests/summaries/test_summary_api.py -q` fails on missing route/query assertions; commit RED test and record SHA/output.

**Dependencias:** T2, T9

### T16: GREEN — Implement summary read and request-status API

**Tracking:** Issue #284 · Card task_c83508cfb0c54e80

**Archivo:** `backend/app/summaries/router.py`; `backend/app/summaries/service.py`; `backend/app/summaries/repository.py`; `backend/app/main.py`
**Acción:** Implement GET current-summary, latest request status, and event-specific status routes with the designed ownership and `require_sales` checks. Return the highest-generation successful summary, 404 if none; latest status selects highest accepted generation. Register `/summary-requests/latest` before `/{event_id}` and expose no provider exception details.

**Criterio de Completado:** T15's RED tests pass: `cd backend && pytest tests/summaries/test_summary_api.py -q`.

**Dependencias:** T15 (mandatory RED→GREEN), T12

## Fase 4: Shared Contracts and Web Experiences

### T17: RED — Specify shared summary/template/status API contracts

**Tracking:** Issue #285 · Card task_5419615ead9a41b7

**Archivo:** `packages/shared-types/src/index.test.ts` (or the package's existing test location, confirmed before editing)
**Acción:** Add contract tests for the approved `MeetingSummary`, `SummaryRequestStatus`, `SummaryTemplate`, and `TemplateCategory` field names, including camel-case UI contracts and status union values. If the package has no test runner/location, stop and report the exact infrastructure gap to Ansel rather than inventing a runner.

**Criterio de Completado:** Before type implementation, the configured shared-types test command fails specifically on absent contract types; record the actual command from `packages/shared-types/package.json` and RED evidence.

**Dependencias:** Ninguna

### T18: GREEN — Add shared summary and template TypeScript contracts

**Tracking:** Issue #286 · Card task_8c8c8278a7a7465e

**Archivo:** `packages/shared-types/src/index.ts`
**Acción:** Add the four interfaces exactly as designed, including `SummaryRequestStatus` lifecycle union and optional category id; preserve existing exports and do not add fields/semantics not specified.

**Criterio de Completado:** T17's RED contract check passes and `npm run typecheck` from `packages/shared-types`' configured package context succeeds; if that package has no independent script, use the verified root `npm run typecheck`.

**Dependencias:** T17 (mandatory RED→GREEN)

### T19: RED — Specify summary presentation, content preservation, empty/polling states (P2/P5)

**Tracking:** Issue #287 · Card task_7218af0f45084aa5

**Archivo:** `frontend/src/components/SummarySection.test.tsx` (create)
**Acción:** Add component tests for a distinct summary section, topic and ordered key points, neutral 404 empty state only when no request is pending/running, resuming latest request on mount, post-request polling, refresh on success, preserving an older summary on terminal failure, and retrying status after a network error. Assert displayed/copyable content but not unspecified serialization.

**Criterio de Completado:** Before component implementation, `cd frontend && npm run test -- --run src/components/SummarySection.test.tsx` fails on missing component/behaviors; commit RED test and record SHA/output.

**Dependencias:** T16, T18

### T20: GREEN — Implement frontend API client and summary section

**Tracking:** Issue #288 · Card task_3f62434d35cb4dd4

**Archivo:** `frontend/src/api.ts`; `frontend/src/components/SummarySection.tsx`; `frontend/src/components/TranscriptView.tsx`
**Acción:** Implement the summary/status API functions and `listTemplates` needed by the summary request selector, with explicit snake_case-to-camelCase mapping and designed 404 behavior. This task owns only summary/status endpoints plus `listTemplates` in `frontend/src/api.ts`; T24 owns the remaining template/category settings endpoints. Render summary in its own section, implement request selection/status polling and the tested empty/error/success behavior. Use only the caller's templates, identify the configured default, and do not invent no-default fallback or fixed layout.

**Criterio de Completado:** T19 RED tests pass with `cd frontend && npm run test -- --run src/components/SummarySection.test.tsx`; `cd frontend && npm run typecheck` succeeds.

**Dependencias:** T19 (mandatory RED→GREEN), T16, T18, T6 (template list API prerequisite)

### T21: RED — Specify copy/download actions for available summaries (P2/P6)

**Tracking:** Issue #289 · Card task_671b8385c0e345fe

**Archivo:** `frontend/src/components/SummarySection.test.tsx` (extend)
**Acción:** Add failing tests that copy and download actions are available for an available summary, clipboard success/failure states behave as designed, and downloaded/copied content preserves topic and key-point content without fixing serialization, MIME type, extension or filename beyond the design's specified filename (if applicable).

**Criterio de Completado:** Before action implementation, `cd frontend && npm run test -- --run src/components/SummarySection.test.tsx` fails on missing action behavior; commit RED test and record SHA/output.

**Dependencias:** T19

### T22: GREEN — Implement summary copy/download controls

**Tracking:** Issue #290 · Card task_76f39781713f40d6

**Archivo:** `frontend/src/components/SummarySection.tsx`
**Acción:** Add copy and download actions for the currently available summary content; provide local success/failure feedback and preserve all required content. Do not infer an unspecified serialization or file format.

**Criterio de Completado:** T21 RED tests pass: `cd frontend && npm run test -- --run src/components/SummarySection.test.tsx`.

**Dependencias:** T21 (mandatory RED→GREEN), T20

### T23: RED — Specify web template settings experience

**Tracking:** Issue #291 · Card task_1bc73c1cd5944767

**Archivo:** `frontend/src/components/TemplateSettingsView.test.tsx` (create)
**Acción:** Add component tests for listing personal templates, marking the personal default, creating multiple templates with opaque instructions, editing an owned template, optional category assignment and category creation, and setting an owned template as default. Do not assert a template grammar or any seed template.

**Criterio de Completado:** Before settings implementation, `cd frontend && npm run test -- --run src/components/TemplateSettingsView.test.tsx` fails on missing view/behaviors; commit RED test and record SHA/output.

**Dependencias:** T8, T18

### T24: GREEN — Implement web template settings view and API integration

**Tracking:** Issue #292 · Card task_66a4a20054504d35

**Archivo:** `frontend/src/api.ts`; `frontend/src/components/TemplateSettingsView.tsx`; `frontend/src/App.tsx`
**Acción:** Implement only the settings-specific API calls in `frontend/src/api.ts` (`createTemplate`, `updateTemplate`, `listCategories`, `createCategory`, and `setDefaultTemplate`), reusing T20's `listTemplates`; implement the settings view including create/edit, optional category, category creation, default identification/selection, and navigation entry in `App.tsx`. Instructions remain an opaque string and PATCH category field-presence semantics are preserved. Consume the default setter's 204 response without JSON parsing.

**Criterio de Completado:** T23's RED tests pass with `cd frontend && npm run test -- --run src/components/TemplateSettingsView.test.tsx`; `cd frontend && npm run typecheck` succeeds.

**Dependencias:** T23 (mandatory RED→GREEN), T6, T8, T18, T20 (shared `frontend/src/api.ts` prerequisite)

## Fase 5: Integration and Validation

### T25: RED — Specify end-to-end summary and template integration invariants (P1/P3/P5/P7/P8)

**Tracking:** Issue #293 · Card task_b9d277de22d5429b

**Archivo:** `backend/tests/integration/test_summary_pipeline.py` (extend)
**Acción:** Add synthetic-fixture end-to-end tests for explicit/default template selection, immutable request snapshot across retries, distinct generations, duplicate event delivery no-op, current-success selection, status lifecycle, transcript-coupled deletion, and the authorized request→outbox→dispatcher→worker flow. Assert transcript commit alone does not generate a summary; do not use real transcripts or assert unresolved no-default behavior.

**Criterio de Completado:** Before final integration wiring, `cd backend && pytest tests/integration/test_summary_pipeline.py -q` fails on missing integrated path; commit RED test and record exact candidate SHA/output.

**Dependencias:** T10, T12, T14, T16

### T26: GREEN — Complete integration wiring and verify required backend suites

**Tracking:** Issue #294 · Card task_4a670bbfbb2c4448

**Archivo:** `backend/app/main.py`; `backend/app/worker.py`; `backend/app/summaries/`; `backend/app/templates/`
**Acción:** Complete only the integration wiring needed for the approved request/outbox/dispatcher/worker/read path and registered routers; ensure summary generation is not triggered by transcript commit. Do not add a Compose service or broader retention policy.

**Criterio de Completado:** T25's RED cases pass; `cd backend && pytest tests/templates tests/summaries -q` and `cd backend && pytest tests/integration/test_summary_pipeline.py -q` both pass. Provider-backed cases require verified D14 binding.

**Dependencias:** T25 (mandatory RED→GREEN), T6, T10, T12, T14, T16

### T27: Validate frontend, backend static checks and complete candidate

**Tracking:** Issue #295 · Card task_de5f12f115264960

**Archivo:** `frontend/src/`; `backend/` (validation only)
**Acción:** Run configured frontend and backend validation on the integrated candidate; fix only in-scope defects through the issue workflow, keeping tests required. No implementation scope is added by this validation task.

**Criterio de Completado:** `cd frontend && npm run typecheck && npm run test`; `cd backend && ruff check . && mypy .`; and the relevant backend suites from T26 pass on the same candidate. Record exact candidate SHA and outputs; do not claim deployment or product acceptance.

**Dependencias:** T20, T22, T24, T26

## Dependency DAG and rationale

- T1 → T2: required RED→GREEN persistence assertions; T2 enables database-backed template/summary work.
- T3 → T4: required RED→GREEN pure resolver properties.
- T2 → T5 → T6 → T7 → T8: test-before-code for owned template CRUD and default setting; T8 also uses the resolver T4.
- T2 + T8 → T9 → T10: request semantics depend on persistence and personal default selection; T9's RED evidence precedes outbox/request implementation.
- T2 + T9 → T11 → T12: event-worker RED test precedes worker implementation, which consumes T10's accepted event.
- T10 + T12 → T13 → T14: required-content integration RED precedes engine seam/generation integration. The real provider binding is a separate D14 gate; it does not block independent work.
- T2 + T9 → T15 → T16: summary/status route tests precede route/query implementation; T16 consumes persisted request/summary data.
- T16 + T18 → T19 → T20 → T21 → T22: frontend summary UI tests precede implementation, then copy/download tests precede controls; T6 → T20 because the summary selector consumes the implemented own-template list API.
- T8 + T18 → T23 → T24: settings UI tests precede implementation and use the approved template/default API. T20 → T24 serializes their edits to shared `frontend/src/api.ts`; T20 owns summary/status calls and `listTemplates`, while T24 adds only settings-specific template/category calls.
- T25 → T26 → T27: integration RED precedes final wiring; final validation depends on all implementation branches.
- T17 → T18: shared types contract tests precede type additions; T17 must verify the package's real test runner before task execution and report a missing test harness rather than inventing one.
- No other edges are implied by phase order. Independent ready tasks remain parallelizable in separate worktrees. Cross-task RED/GREEN branches must preserve the exact RED commit in the eventual implementation candidate as required by design correction 8.

## Validation prerequisites and assumptions

- Run backend commands from repository root as `cd backend && ...`; use the installed project test/runtime environment, synthetic fixtures, and test database setup already configured in the repository. Design confirms `hypothesis` in backend dev dependencies and gives the backend suite commands above.
- Run frontend commands from repository root as `cd frontend && ...`; use the existing Vitest/Testing Library configuration cited by the design.
- Design specifies `cd backend && ruff check . && mypy .`, `cd frontend && npm run typecheck && npm run test`, and the focused suite commands used above. Do not use `make clean` or real meeting data.
- A direct standalone test command/location for `packages/shared-types` is not established in the approved design. T17 is explicitly conditional on verifying the actual package test configuration; if absent, return the exact technical gap to Ansel before implementation instead of fabricating a command or test harness.
- The `PRODUCT_BASELINE.md` checked into the task branch is not the assigned approved snapshot; authority for this plan is the exact baseline commit/blob listed above, plus the approved requirements/design and Fer's documented 2026-10-16 template decision. No assumption beyond those sources is introduced.
