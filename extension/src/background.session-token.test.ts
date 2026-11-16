// Session credential policy in the service worker: the access token lives only in chrome.storage.session
// and the refresh token only in chrome.storage.local, uploads without a valid session stay queued
// (never lost, never counted as failures), an expired access token is renewed silently, and the
// legacy synced token is deleted on start.
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { IDBFactory, IDBKeyRange } from "fake-indexeddb";
import { createCompletion } from "./recording-db";

const { assembleBlob, clearSession } = vi.hoisted(() => ({
  assembleBlob: vi.fn(async () => new Blob(["synthetic recording"])),
  clearSession: vi.fn(async () => undefined),
}));
vi.mock("./recording-db", async (importOriginal) => ({
  ...await importOriginal<typeof import("./recording-db")>(), assembleBlob, clearSession,
}));

type Listener = (message: Record<string, unknown>, sender: unknown, sendResponse: (response: unknown) => void) => unknown;

interface StoredJob { status: string; retryCount: number }

async function readJobs(): Promise<StoredJob[]> {
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open("sauri-upload-queue", 2);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  if (!db.objectStoreNames.contains("jobs")) { db.close(); return []; }
  return new Promise((resolve, reject) => {
    const request = db.transaction("jobs", "readonly").objectStore("jobs").getAll();
    request.onsuccess = () => { db.close(); resolve(request.result); };
    request.onerror = () => reject(request.error);
  });
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 60));
const uploaded = new Response(JSON.stringify({ recording_id: "synthetic-recording", state: "queued" }), { status: 200 });

let session: Record<string, unknown>;
let local: Record<string, unknown>;
let listener: Listener;
let fetchMock: Mock;
let syncRemove: Mock;
let syncSet: Mock;
let localRemove: Mock;
let setAccessLevel: Mock;

type FetchHandler = (url: string, init?: RequestInit) => Promise<Response>;

const bearerOf = (init?: RequestInit) => (init?.headers as Record<string, string> | undefined)?.Authorization;

async function boot(initialSession: Record<string, unknown>, initialLocal: Record<string, unknown> = {}, handler?: FetchHandler) {
  vi.resetModules();
  globalThis.indexedDB = new IDBFactory();
  globalThis.IDBKeyRange = IDBKeyRange;
  session = { sauriState: { status: "idle" }, ...initialSession };
  local = { ...initialLocal };
  fetchMock = vi.fn(handler ?? (async () => uploaded.clone()));
  syncRemove = vi.fn(async () => undefined);
  syncSet = vi.fn(async () => undefined);
  localRemove = vi.fn(async () => undefined);
  setAccessLevel = vi.fn(async () => undefined);
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  await createCompletion({
    sessionId: "synthetic-session", meetingId: "synthetic-meeting", provider: "meet",
    capturedTabId: 7, status: "finalizing", updatedAt: 1,
  });
  vi.stubGlobal("chrome", {
    action: { onClicked: { addListener: vi.fn() }, setBadgeText: vi.fn(), setBadgeBackgroundColor: vi.fn() },
    alarms: { create: vi.fn(), onAlarm: { addListener: vi.fn() } },
    runtime: {
      onInstalled: { addListener: vi.fn() }, onStartup: { addListener: vi.fn() },
      onMessage: { addListener: (fn: Listener) => { listener = fn; } },
      getURL: (path: string) => path, getContexts: vi.fn(async () => []), sendMessage: vi.fn(),
    },
    sidePanel: { setPanelBehavior: vi.fn(async () => undefined), open: vi.fn() },
    storage: {
      session: {
        get: vi.fn(async (keys: string | string[]) => Object.fromEntries([keys].flat().filter((key) => key in session).map((key) => [key, session[key]]))),
        set: vi.fn(async (values: Record<string, unknown>) => { Object.assign(session, values); }),
        remove: vi.fn(async (key: string) => { delete session[key]; }),
        setAccessLevel,
      },
      sync: { remove: syncRemove, set: syncSet, get: vi.fn() },
      local: {
        get: vi.fn(async (key: string) => (key in local ? { [key]: local[key] } : {})),
        set: vi.fn(async (values: Record<string, unknown>) => { Object.assign(local, values); }),
        remove: vi.fn(async (key: string) => { localRemove(key); delete local[key]; }),
      },
    },
    tabs: { onRemoved: { addListener: vi.fn() }, onUpdated: { addListener: vi.fn() }, query: vi.fn(async () => []), create: vi.fn(async () => ({ id: 1 })), sendMessage: vi.fn(async () => undefined) },
  });
  await import("./background");
  listener({ type: "recording-stopped", size: 20, mimeType: "video/webm", sessionId: "synthetic-session" }, {}, vi.fn());
  await settle();
}

const ingestionCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/ingestion/upload"));

describe("service worker session token policy", () => {
  beforeEach(() => {
    vi.spyOn(console, "log").mockImplementation(() => undefined);
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("without a token keeps the upload queued, uncounted, and asks for sign-in", async () => {
    await boot({});
    expect(ingestionCalls()).toHaveLength(0);
    expect(await readJobs()).toEqual([expect.objectContaining({ status: "pending", retryCount: 0 })]);
    expect(session.sauriSignInRequired).toBe(true);
    expect(clearSession).not.toHaveBeenCalled();
  });

  it("keeps waiting across repeated alarms and never burns retries while signed out", async () => {
    await boot({});
    for (let attempt = 0; attempt < 5; attempt++) {
      listener({ type: "session-restored" }, {}, vi.fn());
      await settle();
    }
    expect(ingestionCalls()).toHaveLength(0);
    expect(await readJobs()).toEqual([expect.objectContaining({ status: "pending", retryCount: 0 })]);
  });

  it("resumes the queued upload once the panel reports a fresh sign-in", async () => {
    await boot({});
    session.sauriSessionToken = "fresh-token";
    delete session.sauriSignInRequired;
    const response = vi.fn();
    listener({ type: "session-restored" }, {}, response);
    await settle();
    expect(response).toHaveBeenCalledWith({ ok: true });
    const [[, init]] = ingestionCalls();
    expect((init as RequestInit).headers).toEqual({ Authorization: "Bearer fresh-token" });
    expect(await readJobs()).toEqual([expect.objectContaining({ status: "done", retryCount: 0 })]);
  });

  it("uploads with the session token as the only credential", async () => {
    await boot({ sauriSessionToken: "live-token" });
    const [[url, init]] = ingestionCalls();
    expect(String(url)).not.toContain("live-token");
    expect((init as RequestInit).headers).toEqual({ Authorization: "Bearer live-token" });
    expect(await readJobs()).toEqual([expect.objectContaining({ status: "done" })]);
    expect(session.sauriSignInRequired).toBeUndefined();
  });

  it("treats a 401 as an expired session: drops the token, releases the job without a retry penalty", async () => {
    await boot({ sauriSessionToken: "expired-token" });
    // The first attempt succeeded in boot(); queue a second recording that gets a 401.
    fetchMock.mockImplementation(async () => new Response("", { status: 401 }));
    await createCompletion({ sessionId: "second-session", meetingId: "second-meeting", provider: "meet", capturedTabId: 7, status: "finalizing", updatedAt: 2 });
    session.sauriSessionToken = "expired-token";
    listener({ type: "recording-stopped", size: 20, mimeType: "video/webm", sessionId: "second-session" }, {}, vi.fn());
    await settle();
    expect(session.sauriSessionToken).toBeUndefined();
    expect(session.sauriSignInRequired).toBe(true);
    expect(await readJobs()).toEqual(expect.arrayContaining([expect.objectContaining({ status: "pending", retryCount: 0 })]));
  });

  it("keeps a token the user signed in with while the upload was in flight when the old one is rejected (#1113)", async () => {
    await boot({ sauriSessionToken: "expired-token" });
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) => {
      if (bearerOf(init) !== "Bearer expired-token") return uploaded.clone();
      session.sauriSessionToken = "fresh-token"; // Signed in again during the (long) upload.
      return new Response("", { status: 401 });
    });
    await createCompletion({ sessionId: "second-session", meetingId: "second-meeting", provider: "meet", capturedTabId: 7, status: "finalizing", updatedAt: 2 });
    listener({ type: "recording-stopped", size: 20, mimeType: "video/webm", sessionId: "second-session" }, {}, vi.fn());
    await settle();
    expect(session.sauriSessionToken).toBe("fresh-token");
    expect(session.sauriSignInRequired).toBeUndefined();
    // The retry used the newer token without asking the server to refresh anything.
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/auth/refresh"))).toHaveLength(0);
    expect(await readJobs()).toEqual(expect.arrayContaining([expect.objectContaining({ status: "done", retryCount: 0 })]));
  });

  it("deletes the legacy synced token on start without copying it anywhere", async () => {
    await boot({});
    expect(syncRemove).toHaveBeenCalledWith("authToken");
    expect(localRemove).toHaveBeenCalledWith("authToken");
    expect(syncSet).not.toHaveBeenCalled();
    expect(session.sauriSessionToken).toBeUndefined();
    expect(setAccessLevel).toHaveBeenCalledWith({ accessLevel: "TRUSTED_CONTEXTS" });
  });

  it("rejects a session-restored message that comes from a web page or content script", async () => {
    await boot({});
    const response = vi.fn();
    listener({ type: "session-restored" }, { tab: { id: 3 } }, response);
    expect(response).toHaveBeenCalledWith(expect.objectContaining({ ok: false }));
  });

  describe("refresh token (silent sign-in)", () => {
    const refreshCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/v1/auth/refresh"));
    const refreshReply = (access: string, refresh: string) =>
      new Response(JSON.stringify({ access_token: access, refresh_token: refresh, expires_in: 3600 }), { status: 200 });

    it("after a restart only the refresh token is left: it signs in silently and resumes the queued upload", async () => {
      await boot({}, { sauriRefreshToken: "refresh-1" }, async (url, init) => {
        if (url.endsWith("/auth/refresh")) {
          expect(JSON.parse(String(init?.body))).toEqual({ refresh_token: "refresh-1" });
          return refreshReply("access-2", "refresh-2");
        }
        return uploaded.clone();
      });
      expect(refreshCalls()).toHaveLength(1);
      expect(session.sauriSessionToken).toBe("access-2");
      expect(local.sauriRefreshToken).toBe("refresh-2");
      expect(session.sauriSignInRequired).toBeUndefined();
      const [[, init]] = ingestionCalls();
      expect(bearerOf(init as RequestInit)).toBe("Bearer access-2");
      expect(await readJobs()).toEqual([expect.objectContaining({ status: "done", retryCount: 0 })]);
    });

    it("an expired access token is renewed once and the upload is retried once with the new one", async () => {
      await boot({ sauriSessionToken: "expired-token" }, { sauriRefreshToken: "refresh-1" }, async (url, init) => {
        if (url.endsWith("/auth/refresh")) return refreshReply("access-2", "refresh-2");
        return bearerOf(init) === "Bearer access-2" ? uploaded.clone() : new Response("", { status: 401 });
      });
      expect(ingestionCalls().map(([, init]) => bearerOf(init as RequestInit))).toEqual(["Bearer expired-token", "Bearer access-2"]);
      expect(refreshCalls()).toHaveLength(1);
      expect(local.sauriRefreshToken).toBe("refresh-2");
      expect(await readJobs()).toEqual([expect.objectContaining({ status: "done", retryCount: 0 })]);
    });

    it("a refused refresh clears both credentials and the queued upload waits for sign-in without a retry penalty", async () => {
      await boot({ sauriSessionToken: "expired-token" }, { sauriRefreshToken: "refresh-1" }, async (url) =>
        new Response(url.endsWith("/auth/refresh") ? "{}" : "", { status: 401 }));
      expect(session.sauriSessionToken).toBeUndefined();
      expect(local.sauriRefreshToken).toBeUndefined();
      expect(session.sauriSignInRequired).toBe(true);
      expect(ingestionCalls()).toHaveLength(1); // Never retried without a session.
      expect(await readJobs()).toEqual([expect.objectContaining({ status: "pending", retryCount: 0 })]);
    });

    it("an unreachable server keeps both credentials and does not ask for sign-in", async () => {
      await boot({}, { sauriRefreshToken: "refresh-1" }, async () => { throw new TypeError("offline"); });
      expect(local.sauriRefreshToken).toBe("refresh-1");
      expect(session.sauriSignInRequired).toBeUndefined();
      expect(await readJobs()).toEqual([expect.objectContaining({ status: "pending", retryCount: 0 })]);
    });

    it("never writes the refresh token to synced or session storage", async () => {
      await boot({}, { sauriRefreshToken: "refresh-1" }, async (url) =>
        url.endsWith("/auth/refresh") ? refreshReply("access-2", "refresh-2") : uploaded.clone());
      expect(syncSet).not.toHaveBeenCalled();
      expect(JSON.stringify(session)).not.toMatch(/refresh-/);
    });
  });
});
