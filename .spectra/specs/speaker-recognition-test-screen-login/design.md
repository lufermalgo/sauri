# Design — Owner-Run Speaker-Recognition Test Screen Login

## Summary

The speaker-recognition test screen already exists in the internal React SPA and its authenticated API calls use the `sauri_token` local-storage convention. The existing API provides `POST /api/v1/auth/login` with an email/password request and a JWT response, but the screen currently has no sign-in boundary; users must supply a token manually. This change adds only the login and local logout affordances required to enter and leave this test flow. It does not redesign authentication or change the backend contract.

1. Add a login view at the speaker-test entry boundary when `sauri_token` is absent.
2. Submit credentials through the existing frontend HTTP module to the existing backend login endpoint.
3. Persist only the returned `access_token` under the existing `sauri_token` key; existing authenticated calls continue to send it as a Bearer token.
4. Render the existing speaker test controls only after a token is present, and add local logout that removes the token and returns to login.
5. Add focused frontend unit/component tests for successful and rejected login, token persistence, test-screen gating, and logout.

## Key Design Decisions

**Scope the session gate to the speaker-test view, not the entire SPA.** Place the gate around the `speaker-test` branch in `frontend/src/App.tsx` (or an equally narrow wrapper owned by that branch); leave meeting list, registration, and transcript view behavior unchanged. *Alternatives rejected:* a global route guard or app-wide auth context would expand a test-screen utility into general authentication policy, explicitly out of scope.

**Use the existing API boundary and login contract.** Add a focused `login(email, password)` API function in `frontend/src/api.ts` calling `POST /api/v1/auth/login` with JSON `{email, password}` and consuming `{access_token, token_type, expires_in}` as defined by `backend/app/auth/schemas.py`. The returned token is the only response value persisted for this feature; authenticated speaker-screen requests already read `sauri_token` and send `Authorization: Bearer <token>`. *Alternatives rejected:* direct `fetch` from a component violates the frontend's single HTTP layer; adding a new endpoint or altering backend request/response contracts is unnecessary and prohibited.

**Keep session persistence consistent with the existing frontend convention.** Read and write the literal existing key `sauri_token` in `frontend/src/api.ts` (or export narrow session helpers from that module if needed to avoid duplicating the key). On success, persist `access_token`, update the visible state to the authenticated screen, and clear the password from component state. Do not persist the password, response object, or additional profile/session metadata. On logout, remove only `sauri_token` and return to the unauthenticated speaker-test state. *Alternatives rejected:* cookies, a new storage abstraction, refresh-token machinery, and server-side revocation change the existing convention or exceed scope.

**Keep login component-local and ephemeral.** The login form owns email/password input values and a pending/error state; do not add an app-wide identity store. While submission is pending, prevent duplicate submission. A rejected response or network failure leaves the view unauthenticated, stores no token from that attempt, and displays a visible generic failure indication; do not surface credential-specific distinctions or log credentials. *Alternatives rejected:* storing credentials or global auth state adds unnecessary exposure and scope. Exact visual copy/layout is not specified by requirements and remains ordinary implementation detail.

**Do not infer token expiry or add policy.** `expires_in` is part of the existing response contract but the requirements only prescribe local presence/removal of `access_token`; this design adds no automatic expiry, refresh, revocation, or broad authorization behavior. Authenticated API failures remain governed by existing API behavior. *Alternatives rejected:* expiry timers and global 401 handling would create new policy and affect unrelated frontend flows.

## Architecture

The owner opens the existing SPA's speaker-recognition test view. The view checks the current token convention; an absent value selects the login form, while a present value selects the existing screen plus logout. Login requests use `api.ts` and the current backend endpoint. After persistence, the existing API header helper supplies the same Bearer token to authenticated requests. Logout is local-only.

```mermaid
graph TD
    Owner[Owner] --> App[frontend/src/App.tsx]
    App --> Gate{speaker-test view and token present?}
    Gate -->|No| Login[Speaker test login form]
    Gate -->|Yes| Screen[SpeakerRecognitionTestScreen]
    Login -->|login(email, password)| API[frontend/src/api.ts]
    API -->|POST /api/v1/auth/login| Auth[Existing backend auth router]
    Auth -->|access_token, token_type, expires_in| API
    API -->|save access_token as sauri_token| Storage[Browser localStorage]
    Storage -->|Bearer token| API
    Screen -->|existing authenticated API calls| API
    Screen -->|logout removes sauri_token| Storage
```

```mermaid
sequenceDiagram
    participant O as Owner
    participant UI as App speaker-test gate
    participant API as frontend/src/api.ts
    participant Auth as POST /api/v1/auth/login
    participant LS as localStorage
    O->>UI: Open speaker test
    UI->>LS: Read sauri_token
    alt token absent
        UI-->>O: Show email/password login
        O->>UI: Submit credentials
        UI->>API: login(email, password)
        API->>Auth: POST JSON {email, password}
        alt successful response
            Auth-->>API: {access_token, token_type, expires_in}
            API->>LS: setItem("sauri_token", access_token)
            UI-->>O: Show existing test screen and logout
        else rejected or request failure
            Auth-->>API: error / no completed response
            API-->>UI: reject
            UI-->>O: Remain unauthenticated; show failure
        end
    else token present
        UI-->>O: Show existing test screen and logout
    end
    O->>UI: Activate logout
    UI->>LS: removeItem("sauri_token")
    UI-->>O: Return to login state
```

## Components and Interfaces

### 1. Speaker-test view gate (`frontend/src/App.tsx`)

Keep existing `View` navigation. The `speaker-test` branch chooses between the login affordance and the current `SpeakerRecognitionTestScreen` based on `localStorage.getItem("sauri_token")`. Provide a logout action only in the authenticated branch. Logout clears the token and updates component state so the gate immediately renders login without requiring a page reload. Avoid changing other view branches or imposing authentication on the broader SPA.

### 2. Login form and API operation (`frontend/src/components/` and `frontend/src/api.ts`)

Use a focused login component colocated with frontend UI components (suggested `frontend/src/components/SpeakerTestLogin.tsx`); it accepts a successful-login callback and owns transient form values, pending state, and visible error state. The exact exported component name can follow the implementation convention, but it must remain specific to this test-screen flow.

```typescript
export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export async function login(
  email: string,
  password: string
): Promise<LoginResponse>;
```

`login` sends JSON to `${BASE_URL}/api/v1/auth/login`, uses the existing response error handling, and returns the response without storing credentials or introducing a second HTTP mechanism. Persist only the successful `access_token` using the existing key; do not use a token from an unsuccessful/non-2xx response. Existing authenticated API functions continue using `getAuthHeaders()` and the established Bearer convention.

### 3. Existing authentication endpoint (`backend/app/auth/`)

No backend code changes. Reuse `router.py`'s `POST /api/v1/auth/login`, `LoginRequest` (`email`, `password`) and `LoginResponse` (`access_token`, `token_type`, `expires_in`). Preserve the endpoint's current generic rejection behavior. There is no logout endpoint or token revocation in this design.

### Surface placement and deployment impact

| Surface / artifact | Placement and change | Tests | Migration / deployment |
| --- | --- | --- | --- |
| Web frontend | Modify `frontend/src/App.tsx`, `frontend/src/api.ts`; add a focused login UI under `frontend/src/components/` | `frontend/src/api.test.ts`; add focused component/gate tests under `frontend/src/components/` following existing colocated `*.test.tsx` convention | No database migration; no `docker-compose.yml` change |
| Backend API | Reuse existing `backend/app/auth/router.py` and `schemas.py`; no modifications | Existing auth tests are regression evidence; no new backend test required for an unchanged API contract | No migration or service change |
| Chrome extension | No changes | None | None |
| Shared TypeScript package | No changes; response types can remain local to `frontend/src/api.ts` | No package test change | No package change |

## Data and Session State

No new persisted data structure is introduced. The session value is the existing string item `localStorage["sauri_token"] = access_token`. The password exists only in the login component's transient state during entry/submission and must not be written to browser storage, logs, URL parameters, or API error text. The response's `token_type` and `expires_in` are consumed as contract fields but this feature does not add behavior based on them.

## Correctness Properties

**Property 1 — unauthenticated speaker test is gated.** Whenever `localStorage.getItem("sauri_token")` is absent on entry to the speaker-test view, login inputs/action are rendered and test-screen controls are not rendered. (Requirements 1.1, 2.3)

**Property 2 — successful login uses only the existing contract and token convention.** For credentials submitted, the frontend sends exactly the email/password login request to `/api/v1/auth/login`; only a successful response's `access_token` is stored under `sauri_token`, after which existing authenticated requests use `Authorization: Bearer <access_token>`. (Requirements 1.2–1.3, 2.1)

**Property 3 — failed login stays unauthenticated.** For rejected credentials or request failure, the login state remains visible, no access token from that attempt is persisted, and a visible failure indication is rendered. (Requirement 1.4)

**Property 4 — credentials are not persisted.** After either successful or failed submission, no password value is written to localStorage; the successful transition clears the form's password state. (Requirement 1.5)

**Property 5 — logout is local and returns to login.** Activating logout removes `sauri_token`, leaves no server-side logout/revocation call, and immediately renders the unauthenticated login view. (Requirements 2.2, 3.3)

**Property 6 — scope stays bounded.** Login/logout changes neither the backend login contract nor the existing token key/behavior for other authenticated frontend calls, and introduces no account-creation, user-management, identity-provider, or general authentication workflow. (Requirements 3.1–3.4)

## Error Handling

| Scenario | Behavior |
| --- | --- |
| Missing token when opening the speaker test | Render login; do not render authenticated test controls. |
| Login returns non-success or network request rejects | Keep login view; do not save an access token; show a visible generic failure indication. |
| Login is pending | Prevent duplicate submissions; keep authenticated test controls unavailable until success. |
| Login succeeds | Store only `access_token`; clear transient password state and switch to the test screen. |
| Logout activated | Remove `sauri_token` and switch immediately to login; no server request. |
| Existing token present | Permit the speaker test view under the requirement's local-token-presence rule; do not add expiry or validity probes. |

## Testing Strategy

Use the existing frontend Vitest and Testing Library conventions with synthetic credentials and mocked HTTP responses; never use real credentials or customer data.

- **API tests** in `frontend/src/api.test.ts`: assert POST URL, JSON body shape, successful response decoding; assert non-success/network failure rejects and does not persist a token.
- **Component/gate tests** under `frontend/src/components/`: absent token shows login and hides test controls; successful login stores exactly the returned token and reveals test controls; rejected/network-failed login shows a visible error and remains unauthenticated; password is not persisted; logout removes the key and returns to login.
- Use mocked localStorage/fetch or the existing test setup as appropriate. Tests assert observable UI and browser storage behavior; no real backend or database is needed.
- Run `npm run test`, `npm run typecheck`, and `npm run build` from `frontend/` during implementation. No tests were run during design authoring.

## Traceability and Boundaries

This design traces to `.spectra/specs/speaker-recognition-test-screen-login/requirements.md`, SHA-256 `24cebef401386cfde832a32a1219a09518306d562b147579e9440720c115acaa`, exact approved requirements snapshot `68a9d40efad06b28b4cbc137a0841cf96ac0b50d` (Mira approval is reported in the task packet; requirements PR #575 is open and not merged). It reuses the owner-approved baseline version named in the packet, `d738e78d65940f17d209edf9a54af5d34e92e059`, solely as speaker-test context; the requirements explicitly limit this login to that test utility and defer broader authentication policy. The baseline file at that commit labels itself DRAFT, so this design does not rely on it to authorize authentication scope; the approved requirements and the owner-directed scope recorded there are the behavior authority for this artifact. Existing code was inspected at worktree base commit `4b477830bff64463eee8aac4512840106b74f70b`: `frontend/src/App.tsx`, `frontend/src/api.ts`, the speaker-test component/tests, and `backend/app/auth/router.py` plus `schemas.py`.

No implementation, backend contract change, account management, global auth policy, token revocation, or test-screen redesign is authorized by this design.
