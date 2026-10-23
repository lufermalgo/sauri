# Implementation Plan — Owner-Run Speaker-Recognition Test Screen Login

## Phase Summary

| Phase | Description | Tasks | Dependencies |
|---|---|---:|---|
| 1 | RED: API login contract coverage | T-1 | None |
| 2 | GREEN: API login operation | T-2 | T-1 |
| 3 | RED: speaker-test login and session gate coverage | T-3 | None |
| 4 | GREEN: login UI, narrow gate, and local logout | T-4 | T-2, T-3 |

T-1 and T-3 are independent test-first tasks and may proceed concurrently in separate worktrees. T-2 follows its API contract test; T-4 requires both the API operation and the UI/gate tests.

## Phase 1: API Contract Tests (RED)

### T-1: Add failing tests for the existing login endpoint contract

**Files:** `frontend/src/api.test.ts`

**Action:** Add focused Vitest coverage for the planned `login(email, password)` API operation. With synthetic credentials and mocked `fetch`, assert it sends one `POST` to `${BASE_URL}/api/v1/auth/login`, uses JSON content type and exactly `{ email, password }` as its request body, and decodes the existing `{ access_token, token_type, expires_in }` response. Assert non-success responses and rejected network requests reject the operation. Verify invoking the API operation itself does not write the password or response object to `localStorage` (token persistence belongs to the speaker-test UI flow).

**Completion evidence:** The focused test command fails because the planned login operation is not yet implemented; the failure identifies the missing operation or behavior. Tests use only synthetic values and mocked HTTP.

**Validation command:** `npm run test -- src/api.test.ts` from `frontend/`.

**Dependencies:** None.

**Tracking:** Issue #577 · Card task_70925b412489433a

## Phase 2: API Login Operation (GREEN)

### T-2: Implement login through the existing frontend HTTP boundary

**Files:** `frontend/src/api.ts`

**Action:** Add the typed login request/response operation, sending `{ email, password }` to the existing `POST /api/v1/auth/login` endpoint through `fetch` and the existing response error-handling helper. Return the response contract without persisting credentials, introducing a second HTTP layer, or changing `TOKEN_KEY` / existing Bearer behavior.

**Completion evidence:** `npm run test -- src/api.test.ts` passes, including T-1's endpoint, payload, response and failure cases; `npm run typecheck` from `frontend/` passes.

**Validation command:** `npm run test -- src/api.test.ts && npm run typecheck` from `frontend/`.

**Dependencies:** T-1 (mandatory RED-before-GREEN).

**Status:** Done.

**Tracking:** Card task_ae03ab50ef5848e4 · Issue #578 · PR #582

## Phase 3: Speaker-Test Session UI Tests (RED)

### T-3: Add failing tests for the speaker-test gate, login, failure handling, and logout

**Test seam:** `frontend/src/components/SpeakerTestLogin.test.tsx` exercises the exported `App` from `frontend/src/App.tsx` by entering its `speaker-test` branch, the focused `frontend/src/components/SpeakerTestLogin.tsx` component, and mocked `login(email, password)` from `frontend/src/api.ts`. Keep the UI tests colocated in this exact test file.

**Action:** Using Vitest, Testing Library, synthetic credentials, a deferred mocked login response and controlled `localStorage`, cover: (1) absent `sauri_token` renders email/password login and hides authenticated test controls; (2) while login is pending, authenticated test controls remain hidden and a second submit does not call `login` again; (3) successful login stores only returned `access_token` as `sauri_token`, clears the transient password state, then reveals the existing test screen; (4) rejected login and network failure retain the login view, show a generic visible error and do not persist an access token or password; (5) a pre-existing token permits the test screen; and (6) logout removes only `sauri_token`, immediately returns to login, and makes no server logout/revocation request. Keep coverage scoped to the `speaker-test` branch; do not require or encode app-wide authentication behavior.

**Completion evidence:** `npm run test -- src/components/SpeakerTestLogin.test.tsx` fails before implementation because the login component/gate/logout behavior is absent, with assertions identifying each missing behavior. The pending-state test holds the mocked `login` promise unresolved, verifies the test controls remain hidden and the submit control prevents a duplicate call, then resolves it to prove the transition occurs only on success. Tests contain no real credentials or customer data.

**Validation command:** `npm run test -- src/components/SpeakerTestLogin.test.tsx` from `frontend/`.

**Dependencies:** None. This test-writing task is independent of T-1; its mocks may target the designed login API boundary.

**Tracking:** Issue #579 · Card task_0aee40b04cd64702

## Phase 4: Speaker-Test Login and Gate (GREEN)

### T-4: Implement the local login flow only around the speaker-test view

**Files:** `frontend/src/App.tsx` (existing `speaker-test` branch); `frontend/src/api.ts` (`login(email, password)`); add `frontend/src/components/SpeakerTestLogin.tsx`.

**Action:** Implement the login component and its wiring only at the `speaker-test` branch. The component uses transient email/password plus pending and generic error state, prevents duplicate submission while pending, and clears password state after success. Gate authenticated test controls on token presence; on successful API response, store only `access_token` under `sauri_token` and switch to the existing screen; on logout, remove that key and return to login without a server request. Leave other SPA views, the backend contract, and global authentication behavior unchanged.

**Completion evidence:** The focused component tests in `frontend/src/components/SpeakerTestLogin.test.tsx` pass; `npm run test`, `npm run typecheck`, and `npm run build` all pass from `frontend/`. The implementation changes no backend files, database schema, Compose configuration, Chrome extension or shared package. Review the focused diff to confirm the login gate is limited to `speaker-test` and no password or additional session data is persisted.

**Validation command:** `npm run test && npm run typecheck && npm run build` from `frontend/`.

**Dependencies:** T-2 (the API login operation must exist) and T-3 (mandatory RED-before-GREEN UI coverage).

**Status:** Done.

**Tracking:** Issue #580 · Card task_deca27537fae469a · PR #583

## Dependency Graph and Gates

- T-1 → T-2: API tests must be run failing before implementing the operation.
- T-3 → T-4: UI/gate tests must be run failing before implementing the login flow.
- T-2 → T-4: the login UI uses the existing frontend API boundary.
- T-1 and T-3 have no dependency edge and can be scheduled concurrently.

**Security gate:** After implementation and frontend validation, Zev reviews the exact candidate for credential handling, local token storage and scope containment before any implementation PR. Use synthetic test credentials only; never log or persist the password. No token expiry, refresh or revocation behavior is added.

**Product acceptance gate:** This user-visible feature requires Cyrus to record `PRODUCT_ACCEPTED` for the exact candidate version against predeclared user-test criteria before the spec milestone can be considered accepted. This plan does not declare product acceptance.

**Plan boundary:** No account creation, user management, identity-provider integration, backend auth-contract change, server-side logout/revocation, global auth guard, or broader authentication policy is authorized. The frontend commands above use scripts defined in `frontend/package.json`; no backend/database setup is required by the design's test strategy.
