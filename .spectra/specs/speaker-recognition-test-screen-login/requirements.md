# Requirements — Login for Owner-Run Speaker-Recognition Test Screen

## Introduction

Fer requested a minimal email/password login and logout path so the owner can use the existing speaker-recognition test screen without manually provisioning a frontend token. The current frontend API layer reads the JWT from `localStorage` under `sauri_token`; its protected calls send that value as a Bearer token. The existing backend login endpoint accepts email and password and returns `access_token`, `token_type`, and `expires_in`.

**Thesis:** Add only the authentication affordance needed to enter and leave the owner-run test flow while reusing the existing API contract and frontend token convention.

**Scope:** Provide email/password login against `POST /api/v1/auth/login`, persist a successful response's access token under the existing `sauri_token` key, gate access to the owner-run speaker test screen on that session, and expose logout that clears the locally stored token.

**Out of scope:** Account creation, user management, identity-provider integration, a general authentication or authorization redesign, changes to the backend login contract, and server-side token revocation/logout. The approved product baseline explicitly leaves platform authentication and detailed access policy undecided; this owner-directed, limited test-screen utility does not decide those broader product questions.

**Traceability and authority:** Fer explicitly directed this limited addition in the owner message recorded in chat `th_e3f1c608785d4730` (2026-10-23 14:25); Ansel's assigned card `task_9d6581389fa54492` captures its exact scope. The approved baseline at commit `f5ff445fd508983740cd6b5a89c08adafcbb9295` (blob `c43cad6515b01a52037ad9cd4e09010a40477fb4`) supplies the speaker-review/testing context (§§1, 3, 4.B, 9), while §1 and §5/§7 keep platform authentication undecided. This spec does not treat the later draft baseline snapshot in PR #528 as authorization for broader authentication. The dependent owner-run speaker test screen is specified in approved requirements at commit `d0c45a275d5861eabca78d7fa53484bf31b9afc1` (PR #536), and its approved design is commit `de4fd0dba258684f71d88958af9d6c06240bb97d` (PR #549). The API contract was confirmed in `backend/app/auth/schemas.py` and `backend/app/auth/router.py`; the frontend token convention was confirmed in `frontend/src/api.ts` at the worktree base commit `4b477830bff64463eee8aac4512840106b74f70b`.

## Glossary

- **Owner_Test_Screen:** The existing minimal speaker-recognition test surface, specified by `.spectra/specs/speaker-recognition-test-screen/requirements.md`.
- **Login_Session:** The frontend's locally retained JWT value under the `sauri_token` local-storage key, sent by existing API calls as a Bearer token.
- **Authentication_Service:** The existing `POST /api/v1/auth/login` endpoint accepting `{email, password}` and returning `{access_token, token_type, expires_in}`.

## Requirements

### Requirement 1: Authenticate the owner for the test flow

**User Story:** As the Sauri owner, I want to sign in with my email and password, so that I can use the speaker-recognition test screen without manually supplying a JWT.

#### Acceptance Criteria

1. WHEN no `Login_Session` is present and the user opens the Owner_Test_Screen, THE frontend SHALL provide email and password inputs and a login action instead of the authenticated test-screen controls.
2. WHEN the user submits the login action, THE frontend SHALL send the entered email and password to the Authentication_Service using its existing request contract.
3. WHEN the Authentication_Service returns a successful response, THE frontend SHALL save its `access_token` value under the existing `sauri_token` key and use that value as a Bearer token for existing authenticated API calls.
4. WHEN login is rejected by the Authentication_Service, THE frontend SHALL keep the user unauthenticated and provide a visible failure indication without presenting the rejected credentials as authenticated.
5. THE frontend SHALL NOT persist the password as part of the `Login_Session`.

### Requirement 2: Use and end the local login session

**User Story:** As the Sauri owner, I want the test screen to use my login and let me log out, so that access to this test flow follows the locally stored authentication token.

#### Acceptance Criteria

1. WHEN a `Login_Session` is present, THE frontend SHALL use its token through the existing Bearer-token convention for the Owner_Test_Screen's authenticated API calls.
2. WHEN the user activates logout, THE frontend SHALL remove the `sauri_token` value and return to the unauthenticated login state.
3. WHEN the frontend is loaded with no `sauri_token` value, THE frontend SHALL present the unauthenticated login state before allowing access to the Owner_Test_Screen.

### Requirement 3: Keep authentication scope limited

**User Story:** As the Sauri owner, I want this utility to remain limited to the requested test-screen login, so that it does not make broader authentication decisions for Sauri.

#### Acceptance Criteria

1. THE feature SHALL NOT add account creation, user-management workflows, or identity-provider integration.
2. THE feature SHALL NOT change the backend login request or response contract.
3. THE feature SHALL NOT add or imply server-side logout, token revocation, or a general authentication policy beyond the requested local test-screen session.
4. THE feature SHALL NOT change the existing `sauri_token` storage convention for other frontend authenticated API calls.
