// The only place that attaches the access token to a backend request.
//
// A 401 means the access token expired or was revoked. The request is retried once with a token
// obtained by the single-flight refresh (see session-refresh.ts). When the refresh is refused,
// both credentials are cleared and the caller sees InvalidSessionError (the UI shows the login).

import { clearAllSessionTokens, readSessionToken } from "../session-token";
import { ensureAccessToken, refreshAccessToken } from "./session-refresh";
import { validateTransport } from "./transport";

export class InvalidSessionError extends Error {
  constructor() {
    super("Invalid or expired session");
    this.name = "InvalidSessionError";
  }
}

type Attempt<T> = { unauthorized: true } | { unauthorized: false; value: T };

async function attempt<T>(
  url: string,
  init: RequestInit,
  token: string | undefined,
  handle: (response: Response) => Promise<T>,
  timeoutMs: number | undefined,
): Promise<Attempt<T>> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string> | undefined) };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const controller = new AbortController();
  const timeoutId = timeoutMs ? setTimeout(() => controller.abort(), timeoutMs) : undefined;
  try {
    const response = await fetch(url, { ...init, headers, signal: controller.signal });
    if (response.status === 401) return { unauthorized: true };
    return { unauthorized: false, value: await handle(response) };
  } finally {
    if (timeoutId !== undefined) clearTimeout(timeoutId);
  }
}

/**
 * Sends an authenticated request and passes any non-401 response to `handle` (which owns the body
 * and any status checks). Throws InvalidSessionError once the session is over, or a plain Error when
 * the session could not be renewed right now (offline, server error) and is still stored.
 */
export async function authorizedRequest<T>(
  backendUrl: string,
  path: string,
  init: RequestInit,
  handle: (response: Response) => Promise<T>,
  timeoutMs?: number,
): Promise<T> {
  validateTransport(backendUrl);
  const url = `${backendUrl}${path}`;

  // After a browser restart only the refresh token is left: renew silently before the first call.
  // With nothing to renew, the request goes out unauthenticated and the 401 below ends the session.
  const initial = await ensureAccessToken(backendUrl);
  if (initial.status === "unavailable") throw new Error("Session refresh unavailable");
  const token = initial.status === "ok" ? initial.accessToken : undefined;

  const first = await attempt(url, init, token, handle, timeoutMs);
  if (!first.unauthorized) return first.value;

  const renewed = await refreshAccessToken(backendUrl, token);
  if (renewed.status === "unavailable") throw new Error("Session refresh unavailable");
  if (renewed.status === "rejected") throw new InvalidSessionError();

  const retry = await attempt(url, init, renewed.accessToken, handle, timeoutMs);
  if (!retry.unauthorized) return retry.value;
  // Rejected even right after a renewal (the account was revoked): end the session, unless a
  // newer sign-in replaced it while the request was in flight.
  if (await readSessionToken() === renewed.accessToken) await clearAllSessionTokens();
  throw new InvalidSessionError();
}
