import { answersAsSauri, discoverBackendUrl, forgetBackendUrl, rememberedBackendUrl, resolveBackendUrl } from "./backend";

const TOKEN_KEY = "sauriLocalToken";
const TIMEOUT_MS = 10_000;

export class LocalAppUnavailableError extends Error {
  constructor() {
    super("Local app unavailable");
    this.name = "LocalAppUnavailableError";
  }
}

/** The app refused this copy of the extension (its id is not allowed); pairing again cannot help. */
export class ExtensionNotAllowedError extends LocalAppUnavailableError {
  constructor() {
    super();
    this.name = "ExtensionNotAllowedError";
  }
}

/** Stable refusal code of POST /api/v1/local/pair (backend app/infra/http_security.py). */
const EXTENSION_NOT_ALLOWED = "extension_not_allowed";

async function isExtensionRefusal(response: Response): Promise<boolean> {
  if (response.status !== 403) return false;
  try {
    const body: { detail?: unknown } = await response.json();
    return body.detail === EXTENSION_NOT_ALLOWED;
  } catch {
    return false;
  }
}

/** Removes credentials from pre-desktop builds without touching queued recordings. */
export async function migrateLegacyCredentials(): Promise<void> {
  for (const area of ["session", "local", "sync"] as const) {
    await chrome.storage[area].remove(["authToken", "sauriSessionToken", "sauriRefreshToken", "sauriSignInRequired"]);
  }
}

/** Checks the remembered address first and looks again on every candidate when the app no longer answers there. */
export async function isLocalAppAvailable(): Promise<boolean> {
  const known = await rememberedBackendUrl();
  if (known && await answersAsSauri(known)) return true;
  return (await discoverBackendUrl()) !== null;
}

/** Where the local app answers; LocalAppUnavailableError when no Sauri app does. */
export async function requireBackendUrl(): Promise<string> {
  const url = await resolveBackendUrl();
  if (!url) throw new LocalAppUnavailableError();
  return url;
}

async function pair(rejectedToken?: string): Promise<string> {
  const backendUrl = await requireBackendUrl();
  // Local storage is otherwise exposed to content scripts by default.
  await chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });
  const stored = await chrome.storage.local.get(TOKEN_KEY);
  const current = stored[TOKEN_KEY];
  if (typeof current === "string" && current && current !== rejectedToken) return current;
  try {
    const response = await fetch(`${backendUrl}/api/v1/local/pair`, {
      method: "POST", cache: "no-store", credentials: "omit", redirect: "error", signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (await isExtensionRefusal(response)) throw new ExtensionNotAllowedError();
    if (!response.ok) throw new LocalAppUnavailableError();
    const body: { token?: unknown } = await response.json();
    if (typeof body.token !== "string" || !body.token.trim()) throw new LocalAppUnavailableError();
    await chrome.storage.local.set({ [TOKEN_KEY]: body.token });
    return body.token;
  } catch (error) {
    if (error instanceof ExtensionNotAllowedError) throw error;
    // Nothing answers at the remembered address any more: the next call looks again.
    if (error instanceof TypeError) await forgetBackendUrl();
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
