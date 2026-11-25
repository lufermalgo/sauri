import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";
import { DESKTOP_URL, sauriHealth } from "../test-backend";

let local: Record<string, unknown>;
let session: Record<string, unknown>;
let areas: Record<string, { remove: Mock<(keys: string | string[]) => Promise<void>> }>;
beforeEach(() => {
  vi.resetModules();
  local = {};
  // The app was found on the desktop port earlier in this browser session.
  session = { sauriBackendUrl: DESKTOP_URL };
  areas = Object.fromEntries(["session", "local", "sync"].map(area => [area, { remove: vi.fn(async (keys: string | string[]) => {
    if (area === "session") for (const key of [keys].flat()) delete session[key];
  }) }]));
  vi.stubGlobal("chrome", { storage: {
    ...areas,
    session: { ...areas.session,
      get: vi.fn(async (key: string) => ({ [key]: session[key] })),
      set: vi.fn(async (values: Record<string, unknown>) => { Object.assign(session, values); }),
    },
    local: { ...areas.local,
      setAccessLevel: vi.fn(async () => {}),
      get: vi.fn(async (key: string) => ({ [key]: local[key] })),
      set: vi.fn(async (values: Record<string, unknown>) => { Object.assign(local, values); }),
    },
  } });
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ token: "paired" }))));
});
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("local pairing", () => {
  it("pairs automatically, persists locally, and reuses it after context reload", async () => {
    const first = await import("./local-pairing");
    expect(await first.ensureLocalToken()).toBe("paired");
    expect(local.sauriLocalToken).toBe("paired");
    expect(fetch).toHaveBeenCalledWith(`${DESKTOP_URL}/api/v1/local/pair`, expect.objectContaining({ method: "POST", credentials: "omit", redirect: "error" }));
    expect(chrome.storage.local.setAccessLevel).toHaveBeenCalledWith({ accessLevel: "TRUSTED_CONTEXTS" });
    vi.resetModules();
    expect(await (await import("./local-pairing")).ensureLocalToken()).toBe("paired");
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("coalesces concurrent pairing and uses a cross-context Web Lock", async () => {
    const request = vi.fn(async (_name: string, work: () => Promise<string>) => work());
    vi.stubGlobal("navigator", { locks: { request } });
    const { ensureLocalToken } = await import("./local-pairing");
    expect(await Promise.all([ensureLocalToken(), ensureLocalToken()])).toEqual(["paired", "paired"]);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("sauri-local-pairing", expect.any(Function));
  });

  it("keeps a newer token when a stale request is rejected", async () => {
    local.sauriLocalToken = "newer";
    const { ensureLocalToken } = await import("./local-pairing");
    expect(await ensureLocalToken("older")).toBe("newer");
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each([{}, { token: "" }, { token: 1 }])("rejects malformed pairing response %s without storing it", async body => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(body)));
    const { ensureLocalToken, LocalAppUnavailableError } = await import("./local-pairing");
    await expect(ensureLocalToken()).rejects.toBeInstanceOf(LocalAppUnavailableError);
    expect(local).toEqual({});
  });

  it("tells a refused extension copy apart from an unavailable app", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ detail: "extension_not_allowed" }), { status: 403 }));
    const { ensureLocalToken, ExtensionNotAllowedError } = await import("./local-pairing");
    await expect(ensureLocalToken()).rejects.toBeInstanceOf(ExtensionNotAllowedError);
    expect(local).toEqual({});
  });

  it.each([
    new Response(JSON.stringify({ detail: "local_origin_required" }), { status: 403 }),
    new Response("not json", { status: 403 }),
    new Response(JSON.stringify({ detail: "extension_not_allowed" }), { status: 500 }),
  ])("keeps other pairing failures as an unavailable app", async response => {
    vi.mocked(fetch).mockResolvedValue(response);
    const { ensureLocalToken, ExtensionNotAllowedError, LocalAppUnavailableError } = await import("./local-pairing");
    const failure = ensureLocalToken();
    await expect(failure).rejects.toBeInstanceOf(LocalAppUnavailableError);
    await expect(failure).rejects.not.toBeInstanceOf(ExtensionNotAllowedError);
  });

  it.each([401, 403])("renews once on %s, then stops if rejected again", async status => {
    local.sauriLocalToken = "old";
    vi.mocked(fetch).mockImplementation(async url => String(url).endsWith("/pair")
      ? new Response(JSON.stringify({ token: "new" })) : new Response("", { status }));
    const { authorizedRequest } = await import("./api/authorized-fetch");
    await expect(authorizedRequest("/api/v1/meetings/", {}, async r => r.json())).rejects.toThrow("Local app unavailable");
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/pair"))).toHaveLength(1);
  });

  it("reports health without sending credentials and treats an offline or unhealthy app as unavailable", async () => {
    vi.mocked(fetch).mockImplementation(async () => sauriHealth());
    const { isLocalAppAvailable } = await import("./local-pairing");
    expect(await isLocalAppAvailable()).toBe(true);
    expect(fetch).toHaveBeenCalledWith(`${DESKTOP_URL}/health`, expect.objectContaining({ credentials: "omit", cache: "no-store" }));
    vi.mocked(fetch).mockImplementation(async () => new Response("", { status: 503 }));
    expect(await isLocalAppAvailable()).toBe(false);
    expect(session.sauriBackendUrl).toBeUndefined();
    vi.mocked(fetch).mockRejectedValue(new TypeError("offline"));
    expect(await isLocalAppAvailable()).toBe(false);
  });

  it("deletes all legacy credential keys in each storage area, not recording settings", async () => {
    const { migrateLegacyCredentials } = await import("./local-pairing");
    await migrateLegacyCredentials();
    for (const area of Object.values(areas)) expect(area.remove).toHaveBeenCalledWith(["authToken", "sauriSessionToken", "sauriRefreshToken", "sauriSignInRequired"]);
  });

  it("never sends the bearer outside the app's API", async () => {
    local.sauriLocalToken = "private";
    const { authorizedRequest } = await import("./api/authorized-fetch");
    for (const path of ["https://example.invalid/api/v1/meetings/", "//example.invalid/api/", "/health"]) {
      await expect(authorizedRequest(path, {}, async r => r.json())).rejects.toThrow("destination mismatch");
    }
    expect(fetch).not.toHaveBeenCalled();
  });

  it("sends API calls to the address found by discovery", async () => {
    local.sauriLocalToken = "private";
    vi.mocked(fetch).mockImplementation(async () => new Response("[]"));
    const { authorizedRequest } = await import("./api/authorized-fetch");
    expect(await authorizedRequest("/api/v1/meetings/", {}, async r => r.json())).toEqual([]);
    expect(fetch).toHaveBeenCalledWith(`${DESKTOP_URL}/api/v1/meetings/`, expect.anything());
  });

  it("forgets the address when the app stops answering there, so the next call looks again", async () => {
    local.sauriLocalToken = "private";
    vi.mocked(fetch).mockRejectedValue(new TypeError("connection refused"));
    const { authorizedRequest } = await import("./api/authorized-fetch");
    await expect(authorizedRequest("/api/v1/meetings/", {}, async r => r.json())).rejects.toThrow("Local app unavailable");
    expect(session.sauriBackendUrl).toBeUndefined();
  });
});

it("does not mistake a concurrent cached read for renewal of a rejected token", async () => {
  local.sauriLocalToken = "old";
  const { ensureLocalToken } = await import("./local-pairing");
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  vi.mocked(chrome.storage.local.get).mockImplementationOnce(async () => { await gate; return { sauriLocalToken: "old" }; });
  const read = ensureLocalToken();
  const renewal = ensureLocalToken("old");
  expect(await renewal).toBe("paired");
  release();
  await read;
  expect(local.sauriLocalToken).toBe("paired");
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("retries a stale unauthorized request with the token another context already paired", async () => {
  local.sauriLocalToken = "old";
  vi.mocked(fetch).mockImplementation(async (_url, init) => {
    if ((init?.headers as Record<string, string>).Authorization === "Bearer old") {
      local.sauriLocalToken = "newer";
      return new Response("", { status: 401 });
    }
    return new Response("[]");
  });
  const { authorizedRequest } = await import("./api/authorized-fetch");
  expect(await authorizedRequest("/api/v1/meetings/", {}, async r => r.json())).toEqual([]);
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(local.sauriLocalToken).toBe("newer");
});

it("shares one renewal for concurrent unauthorized requests", async () => {
  local.sauriLocalToken = "old";
  vi.mocked(fetch).mockImplementation(async (url, init) => {
    if (String(url).endsWith("/pair")) return new Response(JSON.stringify({ token: "paired" }));
    return (init?.headers as Record<string, string>).Authorization === "Bearer old"
      ? new Response("", { status: 403 }) : new Response("[]");
  });
  const { authorizedRequest } = await import("./api/authorized-fetch");
  const request = () => authorizedRequest("/api/v1/meetings/", {}, async r => r.json());
  expect(await Promise.all([request(), request(), request()])).toEqual([[], [], []]);
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/pair"))).toHaveLength(1);
});

it("bounds an unresponsive health request without credentials", async () => {
  const controller = new AbortController();
  const timeout = vi.spyOn(AbortSignal, "timeout").mockReturnValue(controller.signal);
  vi.mocked(fetch).mockImplementation(async (_url, init) => new Promise((_resolve, reject) => {
    const abort = () => reject(new DOMException("Aborted", "AbortError"));
    if (init!.signal!.aborted) abort();
    else init!.signal!.addEventListener("abort", abort);
  }));
  try {
    const { isLocalAppAvailable } = await import("./local-pairing");
    const result = isLocalAppAvailable();
    controller.abort();
    expect(await result).toBe(false);
    expect(timeout).toHaveBeenCalledWith(5_000);
  } finally { timeout.mockRestore(); }
});
