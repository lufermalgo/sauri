// The only module allowed to touch the API session token.
//
// Policy:
// - The token lives in chrome.storage.session: held in memory by the browser, never
//   written to disk, never replicated to the user's Google account (unlike
//   chrome.storage.sync), cleared when the browser restarts or the extension reloads,
//   and readable only by trusted extension contexts (service worker, side panel,
//   options page) -- never by content scripts or web pages.
// - There is no "remember me": the token is a 60-minute bearer JWT, so persisting it
//   across restarts would buy little and make a stolen disk or synced profile useful.
// - Without a token, uploads stay queued (see background.ts) and the panel asks the
//   user to sign in again; signing in resumes the queue.
// - Legacy builds stored the token in chrome.storage.sync. It is deleted, never copied.

const TOKEN_KEY = "sauriSessionToken";
/** Non-secret flag: queued uploads are waiting for the user to sign in again. */
const SIGN_IN_REQUIRED_KEY = "sauriSignInRequired";
/** Key used by builds before this change (chrome.storage.sync / local). */
const LEGACY_TOKEN_KEY = "authToken";

/** An operation needs a signed-in user but there is no valid token. Carries no secret. */
export class SessionRequiredError extends Error {
  constructor() {
    super("Sign-in required");
    this.name = "SessionRequiredError";
  }
}

/** Keeps session storage away from content scripts (this is also Chrome's default). */
export async function restrictSessionStorageToTrustedContexts(): Promise<void> {
  try {
    await chrome.storage.session.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });
  } catch (error) {
    console.debug("[sauri] Could not restrict session storage access:", error);
  }
}

export async function readSessionToken(): Promise<string | undefined> {
  const stored = await chrome.storage.session.get(TOKEN_KEY);
  const token = stored[TOKEN_KEY];
  return typeof token === "string" && token ? token : undefined;
}

/** Stores a fresh token and clears the pending sign-in prompt. */
export async function storeSessionToken(token: string): Promise<void> {
  await chrome.storage.session.set({ [TOKEN_KEY]: token });
  await chrome.storage.session.remove(SIGN_IN_REQUIRED_KEY);
}

export async function clearSessionToken(): Promise<void> {
  await chrome.storage.session.remove(TOKEN_KEY);
}

/** Records that queued work is blocked until the user signs in again. */
export async function setSignInRequired(): Promise<void> {
  await chrome.storage.session.set({ [SIGN_IN_REQUIRED_KEY]: true });
}

export async function isSignInRequired(): Promise<boolean> {
  const stored = await chrome.storage.session.get(SIGN_IN_REQUIRED_KEY);
  return stored[SIGN_IN_REQUIRED_KEY] === true;
}

/**
 * Deletes the token that older builds left in synced (and local) storage. It is
 * never copied into session storage: the user signs in once more.
 */
export async function purgeLegacyToken(): Promise<void> {
  for (const area of ["sync", "local"] as const) {
    try {
      await chrome.storage[area].remove(LEGACY_TOKEN_KEY);
    } catch (error) {
      console.debug(`[sauri] Could not purge the legacy token from ${area} storage:`, error);
    }
  }
}

/** Calls back when the token or the sign-in prompt changes (e.g. an upload found it expired). */
export function onSessionChanged(listener: () => void): () => void {
  const handler = (changes: Record<string, chrome.storage.StorageChange>, area: string) => {
    if (area === "session" && (TOKEN_KEY in changes || SIGN_IN_REQUIRED_KEY in changes)) listener();
  };
  chrome.storage.onChanged.addListener(handler);
  return () => chrome.storage.onChanged.removeListener(handler);
}
