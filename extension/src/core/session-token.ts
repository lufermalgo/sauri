// The only module allowed to touch the API session credentials.
//
// Policy:
// - The access token (a 60-minute bearer JWT) lives in chrome.storage.session: held in
//   memory by the browser, never written to disk, never replicated to the user's Google
//   account (unlike chrome.storage.sync), cleared when the browser restarts or the
//   extension reloads, and readable only by trusted extension contexts (service worker,
//   side panel, options page) -- never by content scripts or web pages.
// - The refresh token is the one credential that survives a reload or a restart,
//   so it is the only thing stored in chrome.storage.local: on disk in the browser profile,
//   never replicated (not sync) and never in session storage. Trade-off: a credential now
//   sits on disk, bounded by the server-side lifetimes (30 days idle, 90 days absolute),
//   rotated on every use and revocable on the server. chrome.storage.local is not exposed
//   to content scripts or web pages either, and the token is never put in a message or a URL.
// - Without an access token the extension silently exchanges the refresh token for a new
//   one (see api/session-refresh.ts). Only when that is rejected are both credentials
//   cleared, uploads stay queued (see background.ts) and the panel asks the user to sign in.
// - Legacy builds stored the token in chrome.storage.sync. It is deleted, never copied.

const TOKEN_KEY = "sauriSessionToken";
/** The rotating refresh credential; chrome.storage.local only, see the policy above. */
const REFRESH_KEY = "sauriRefreshToken";
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

export async function readRefreshToken(): Promise<string | undefined> {
  const stored = await chrome.storage.local.get(REFRESH_KEY);
  const token = stored[REFRESH_KEY];
  return typeof token === "string" && token ? token : undefined;
}

export async function storeRefreshToken(token: string): Promise<void> {
  await chrome.storage.local.set({ [REFRESH_KEY]: token });
}

export async function clearRefreshToken(): Promise<void> {
  await chrome.storage.local.remove(REFRESH_KEY);
}

/**
 * Drops the refresh token only if it is still the one a rejection was about. A sign-in that
 * finished in the meantime stored a different one, which must survive.
 */
export async function clearRefreshTokenIf(rejectedToken: string | undefined): Promise<boolean> {
  if (!rejectedToken) return false;
  if (await readRefreshToken() !== rejectedToken) return false;
  await clearRefreshToken();
  return true;
}

/** Signs the browser out: both credentials are removed. */
export async function clearAllSessionTokens(): Promise<void> {
  await clearRefreshToken();
  await clearSessionToken();
}

/**
 * Stores the credentials of a fresh sign-in or refresh. The refresh token is written first: it
 * is the one that cannot be re-derived, because the server retires the previous one on use.
 * A response without a refresh token (an older backend) drops any stale one.
 */
export async function storeSessionCredentials(accessToken: string, refreshToken?: string): Promise<void> {
  if (refreshToken) await storeRefreshToken(refreshToken);
  else await clearRefreshToken();
  await storeSessionToken(accessToken);
}

/**
 * Drops the stored token only if it is still the one a rejected request was sent with.
 * A slow request (an upload, a poll) can come back 401 after the user has already signed
 * in again; clearing unconditionally would sign them out of the fresh session. A request
 * sent without a token (`undefined`) can never invalidate a stored one.
 * Returns true when the stored token was removed.
 */
export async function clearSessionTokenIf(rejectedToken: string | undefined): Promise<boolean> {
  if (!rejectedToken) return false;
  if (await readSessionToken() !== rejectedToken) return false;
  await clearSessionToken();
  return true;
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

/** Calls back when a credential or the sign-in prompt changes (e.g. an upload found it expired). */
export function onSessionChanged(listener: () => void): () => void {
  const handler = (changes: Record<string, chrome.storage.StorageChange>, area: string) => {
    if (area === "session" && (TOKEN_KEY in changes || SIGN_IN_REQUIRED_KEY in changes)) listener();
    if (area === "local" && REFRESH_KEY in changes) listener();
  };
  chrome.storage.onChanged.addListener(handler);
  return () => chrome.storage.onChanged.removeListener(handler);
}
