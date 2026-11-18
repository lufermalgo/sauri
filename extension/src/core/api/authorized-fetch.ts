import { BACKEND_URL } from "../backend";
import { ensureLocalToken, LocalAppUnavailableError } from "../local-pairing";
import { validateTransport } from "./transport";

type Attempt<T> = { unauthorized: true } | { unauthorized: false; value: T };

async function attempt<T>(
  url: string,
  init: RequestInit,
  token: string,
  handle: (response: Response) => Promise<T>,
  timeoutMs: number | undefined,
): Promise<Attempt<T>> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string> | undefined) };
  headers["Authorization"] = `Bearer ${token}`;
  const controller = new AbortController();
  const timeoutId = timeoutMs ? setTimeout(() => controller.abort(), timeoutMs) : undefined;
  try {
    let response: Response;
    try {
      response = await fetch(url, { ...init, headers, credentials: "omit", redirect: "error", signal: controller.signal });
    } catch (error) {
      if (error instanceof TypeError) throw new LocalAppUnavailableError();
      throw error;
    }
    if (response.status === 401 || response.status === 403) return { unauthorized: true };
    return { unauthorized: false, value: await handle(response) };
  } finally {
    if (timeoutId !== undefined) clearTimeout(timeoutId);
  }
}

/** Sends a local bearer, pairing again once if the API rejects it. */
export async function authorizedRequest<T>(
  backendUrl: string,
  path: string,
  init: RequestInit,
  handle: (response: Response) => Promise<T>,
  timeoutMs?: number,
): Promise<T> {
  validateTransport(backendUrl);
  if (new URL(backendUrl).origin !== new URL(BACKEND_URL).origin || !path.startsWith("/api/")) {
    throw new Error("Local credential destination mismatch");
  }
  const url = `${backendUrl}${path}`;
  const token = await ensureLocalToken();
  const first = await attempt(url, init, token, handle, timeoutMs);
  if (!first.unauthorized) return first.value;
  const renewed = await ensureLocalToken(token);
  const retry = await attempt(url, init, renewed, handle, timeoutMs);
  if (!retry.unauthorized) return retry.value;
  throw new LocalAppUnavailableError();
}
