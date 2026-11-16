# Authentication and sessions

Scope: `backend/app/auth/`. Hardening delivered in #1069. Cookie or storage changes for the session token are a separate unit.

## Login

`POST /api/v1/auth/login` takes `{email, password}`. Unknown keys are rejected, `email` must be a valid address of at most 254 characters and `password` 1 to 256 characters. A validation error (422) lists field, message and type only; it never echoes the submitted values.

### Rate limiting

Counters live in the `login_attempts` table (migration `025_auth_hardening`), keyed by SHA-256 digests so no email or address is stored. A table, rather than process memory, keeps the counters across restarts and correct if several API processes run.

| Counter | Key | Locks after |
| --- | --- | --- |
| `ip_email` | client address + lower-cased email | 5 failures |
| `email` | lower-cased email | 20 failures |

The failure that reaches the threshold locks the key for 60 s. Each further failure doubles the lock up to 15 min. A key forgets its failures after 30 min without a new failure, and a successful login clears both keys. While a key is locked the password is not checked, and the answer is `429` with `Retry-After`; the body is the same whether the account exists or not.

Known limit: the client address is the direct peer address. Behind a reverse proxy all clients share the proxy address, so the `ip_email` counter then behaves like the `email` one until trusted forwarding is configured. The `email` counter lets an attacker lock one account for at most 15 min at a time, which is why its threshold is higher.

Failures are written to `access_log` (`result = denied`) and to the `sauri.auth` logger with a truncated SHA-256 of the email and the address, never the password. A lockout also logs a warning.

### Timing

An unknown email verifies the submitted password against a dummy Argon2id hash with the live parameters, so a known account with a wrong password and an unknown account cost the same. Accounts whose hash is still PBKDF2 (until their next successful login) are cheaper or dearer than the dummy by the difference between the two schemes.

## Passwords

New hashes are Argon2id (`m=19456 KiB, t=2, p=1`, `argon2-cffi`). The scheme is part of the hash string (`$argon2id$...`). Older `pbkdf2_sha256$...` hashes still verify, with a constant-time comparison, and are replaced by an Argon2id hash after the next successful login. `python -m app.auth.seed_admin` creates Argon2id hashes; `--reset-password` also revokes the admin's sessions.

## Session token (JWT, HS256, PyJWT)

Claims: `sub`, `email`, `name`, `is_sales` (informational), `tv`, `jti`, `iat`, `exp` (60 min).

- The signing secret is mandatory: `JWT_SECRET_FILE` (preferred) or `JWT_SECRET`, at least 32 bytes. The API refuses to start without it (the auth router's lifespan hook fails with a message that never contains the secret). Only `APP_ENV=test` runs without one, using a random per-process secret.
- `tv` is compared with `users.token_version` on every request. `POST /api/v1/auth/logout` (204) increments it, which revokes every session of that user. A token without `tv` (issued before this change) counts as version 0, so existing sessions keep working until they expire or the user logs out.
- Role and profile are read from the `users` row on every request; the `is_sales` claim is never trusted. A role change applies to existing tokens on the next request, and a deleted account stops authenticating.
- Test environment only (`APP_ENV=test`): a token whose user has no row is accepted on its claims, so route tests can mint synthetic users. Any other environment answers 401.

## Deployment notes

- Make sure the JWT secret file exists and holds 32 or more bytes before deploying (`make up` generates a 64-character one).
- Run the migration (`alembic upgrade head`) before starting the new API: it adds `users.token_version` and `login_attempts`.
- Deploying this change does not sign anyone out. Changing the JWT secret does.
