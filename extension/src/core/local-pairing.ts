import { BACKEND_URL } from "./backend";
import { validateTransport } from "./api/transport";

const TOKEN_KEY = "sauriLocalToken";
const TIMEOUT_MS = 10_000;

export class LocalAppUnavailableError extends Error {
  constructor() {
    super("Local app unavailable");
    this.name = "LocalAppUnavailableError";
  }
}

/** Removes credentials from pre-desktop builds without touching queued recordings. */
export async function migrateLegacyCredentials(): Promise<void> {
  for (const area of ["session", "local", "sync"] as const) {
    await chrome.storage[area].remove(["authToken", "sauriSessionToken", "sauriRefreshToken", "sauriSignInRequired"]);
  }
}

export async function isLocalAppAvailable(): Promise<boolean> {
  validateTransport(BACKEND_URL);
  try {
    const response = await fetch(`${BACKEND_URL}/health`, {
      cache: "no-store", credentials: "omit", redirect: "error", signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    return response.ok;
  } catch {
    return false;
  }
}

async function pair(rejectedToken?: string): Promise<string> {
  validateTransport(BACKEND_URL);
  // Local storage is otherwise exposed to content scripts by default.
  await chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });
  const stored = await chrome.storage.local.get(TOKEN_KEY);
  const current = stored[TOKEN_KEY];
  if (typeof current === "string" && current && current !== rejectedToken) return current;
  try {
    const response = await fetch(`${BACKEND_URL}/api/v1/local/pair`, {
      method: "POST", cache: "no-store", credentials: "omit", redirect: "error", signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!response.ok) throw new LocalAppUnavailableError();
    const body: { token?: unknown } = await response.json();
    if (typeof body.token !== "string" || !body.token.trim()) throw new LocalAppUnavailableError();
    await chrome.storage.local.set({ [TOKEN_KEY]: body.token });
    return body.token;
  } catch {
    throw new LocalAppUnavailableError();
  }
}

const inFlight = new Map<string | undefined, Promise<string>>();

/** Reuses the on-disk local credential; a rejected one is replaced, never refreshed via login. */
export function ensureLocalToken(rejectedToken?: string): Promise<string> {
  const pending = inFlight.get(rejectedToken);
  if (pending) return pending;
  const work = () => pair(rejectedToken);
  const locks = typeof navigator === "undefined" ? undefined : navigator.locks;
  const run = (async () => locks ? await locks.request("sauri-local-pairing", work) : await work())();
  const result = run.finally(() => { inFlight.delete(rejectedToken); });
  inFlight.set(rejectedToken, result);
  return result;
}
