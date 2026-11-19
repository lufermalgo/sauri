// Where the local Sauri app answers. The desktop app listens on 41750; 8000 stays a fallback during the transition
// for installs that still run the previous app (and for the Docker development stack).
import { validateTransport } from "./api/transport";

export const DESKTOP_BACKEND_URL = "http://localhost:41750";
export const LEGACY_BACKEND_URL = "http://localhost:8000";

const configured: string | undefined = import.meta.env.VITE_SAURI_BACKEND_URL;
/** Candidates in order of preference; a build pointed at one backend only tries that one. */
export const BACKEND_CANDIDATES: readonly string[] = configured ? [configured] : [DESKTOP_BACKEND_URL, LEGACY_BACKEND_URL];

/** chrome.storage.session key of the address found last, shared by the extension's own pages. */
export const BACKEND_URL_KEY = "sauriBackendUrl";
const PROBE_TIMEOUT_MS = 5_000;

/**
 * Sauri's /health carries `service: "sauri"`. On the legacy port the exact answer of apps released before that
 * signature (`{"status":"ok"}` and nothing else) is accepted too, so they keep working until they update.
 */
export function isSauriHealth(body: unknown, url: string): boolean {
  if (!body || typeof body !== "object" || Array.isArray(body)) return false;
  const fields = body as Record<string, unknown>;
  if (fields.status !== "ok") return false;
  if (fields.service === "sauri") return true;
  return url === LEGACY_BACKEND_URL && Object.keys(fields).length === 1;
}

/** Whether Sauri, and not another local program, answers at `url`. Never sends credentials. */
export async function answersAsSauri(url: string): Promise<boolean> {
  validateTransport(url);
  try {
    const response = await fetch(`${url}/health`, {
      cache: "no-store", credentials: "omit", redirect: "error", signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
    });
    return response.ok && isSauriHealth(await response.json(), url);
  } catch {
    return false;
  }
}

let remembered: string | undefined;

/** The address found last in this browser session, if it is still one of the candidates. */
export async function rememberedBackendUrl(): Promise<string | undefined> {
  if (remembered) return remembered;
  try {
    const value = (await chrome.storage.session.get(BACKEND_URL_KEY))[BACKEND_URL_KEY];
    if (typeof value === "string" && BACKEND_CANDIDATES.includes(value)) remembered = value;
  } catch {
    // Without session storage the address is found again; it is only a shortcut.
  }
  return remembered;
}

async function remember(url: string | null): Promise<void> {
  remembered = url ?? undefined;
  try {
    if (url) await chrome.storage.session.set({ [BACKEND_URL_KEY]: url });
    else await chrome.storage.session.remove(BACKEND_URL_KEY);
  } catch {
    // Same as above: the in-memory value still serves this page.
  }
}

/** Probes every candidate and remembers the preferred one that answers as Sauri; null when none does. */
export async function discoverBackendUrl(): Promise<string | null> {
  const answers = await Promise.all(BACKEND_CANDIDATES.map(answersAsSauri));
  const found = BACKEND_CANDIDATES.find((_, index) => answers[index]) ?? null;
  await remember(found);
  return found;
}

/** The remembered address, else a fresh discovery. */
export async function resolveBackendUrl(): Promise<string | null> {
  return (await rememberedBackendUrl()) ?? discoverBackendUrl();
}

/** Drops the remembered address once the app stops answering there (it may have moved to the new port). */
export function forgetBackendUrl(): Promise<void> {
  return remember(null);
}
