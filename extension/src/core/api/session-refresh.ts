// Silent renewal of the access token with the rotating refresh token.
//
// The server retires a refresh token the first time it is used and revokes the whole session if it
// ever sees a retired one again. So two refreshes must never run at once with the same token: the
// service worker, the side panel and the options page can all notice an expired access token at the
// same moment. Within a context a single in-flight promise is shared; across contexts a Web Lock
// serializes the work, and the second context finds the access token the first one stored.
//
// The refresh token is read and written only through session-token.ts and is never logged, put in a
// URL or sent anywhere but the refresh and sign-out endpoints.

import {
  clearAllSessionTokens,
  clearRefreshTokenIf,
  clearSessionTokenIf,
  readRefreshToken,
  readSessionToken,
  storeSessionCredentials,
} from "../session-token";
import { validateTransport } from "./transport";

const REFRESH_TIMEOUT_MS = 10_000;
const LOCK_NAME = "sauri-session-refresh";

export type RefreshOutcome =
  /** `accessToken` is valid for requests now. */
  | { status: "ok"; accessToken: string }
  /** The server refused the credential (or there was none): the session is over and both tokens are cleared. */
  | { status: "rejected" }
  /** Offline, timeout or a server error: nothing was cleared, a later attempt may succeed. */
  | { status: "unavailable" };

/** Runs `work` with every other context that uses the session credentials held back (when Web Locks exist). */
export async function withSessionLock<T>(work: () => Promise<T>): Promise<T> {
  const locks = typeof navigator === "undefined" ? undefined : navigator.locks;
  if (!locks) return work();
  return locks.request(LOCK_NAME, work);
}

let inFlight: Promise<RefreshOutcome> | undefined;

/**
 * Exchanges the stored refresh token for a new access token.
 * `rejectedAccessToken` is the token a request was just denied with: when the stored one is already
 * different, another context refreshed first and no server call is made.
 */
export function refreshAccessToken(backendUrl: string, rejectedAccessToken?: string): Promise<RefreshOutcome> {
  if (!inFlight) {
    const run = withSessionLock(() => performRefresh(backendUrl, rejectedAccessToken));
    inFlight = run.finally(() => { inFlight = undefined; });
  }
  return inFlight;
}

/** An access token for a request: the stored one, or a silent refresh when only a refresh token is left. */
export async function ensureAccessToken(backendUrl: string): Promise<RefreshOutcome> {
  const current = await readSessionToken();
  if (current) return { status: "ok", accessToken: current };
  return refreshAccessToken(backendUrl);
}

async function performRefresh(backendUrl: string, rejectedAccessToken: string | undefined): Promise<RefreshOutcome> {
  validateTransport(backendUrl);
  const current = await readSessionToken();
  if (current && current !== rejectedAccessToken) return { status: "ok", accessToken: current };

  const refreshToken = await readRefreshToken();
  if (!refreshToken) {
    await clearSessionTokenIf(rejectedAccessToken);
    return { status: "rejected" };
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REFRESH_TIMEOUT_MS);
  try {
    const response = await fetch(`${backendUrl}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      signal: controller.signal,
    });
    if (response.status === 401) {
      // Only what this attempt used is dropped; a sign-in that finished meanwhile keeps its tokens.
      await clearRefreshTokenIf(refreshToken);
      await clearSessionTokenIf(rejectedAccessToken);
      return { status: "rejected" };
    }
    if (!response.ok) return { status: "unavailable" };
    const body = (await response.json()) as { access_token?: unknown; refresh_token?: unknown };
    if (typeof body.access_token !== "string" || !body.access_token ||
        typeof body.refresh_token !== "string" || !body.refresh_token) {
      return { status: "unavailable" };
    }
    await storeSessionCredentials(body.access_token, body.refresh_token);
    return { status: "ok", accessToken: body.access_token };
  } catch {
    return { status: "unavailable" };
  } finally {
    clearTimeout(timeoutId);
  }
}

/**
 * Signs out of this browser: both credentials are removed first (so the user is signed out even
 * offline), then the server is asked to end this session's refresh family. The portal's own sessions
 * are not touched. A failure to reach the server is not an error: the credential is gone locally and
 * expires on its own server-side.
 */
export async function signOut(backendUrl: string): Promise<void> {
  validateTransport(backendUrl);
  const refreshToken = await withSessionLock(async () => {
    const stored = await readRefreshToken();
    await clearAllSessionTokens();
    return stored;
  });
  if (!refreshToken) return;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REFRESH_TIMEOUT_MS);
  try {
    await fetch(`${backendUrl}/api/v1/auth/refresh/revoke`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      signal: controller.signal,
    });
  } catch {
    // Offline: nothing more to do, see above.
  } finally {
    clearTimeout(timeoutId);
  }
}
