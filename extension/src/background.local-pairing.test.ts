import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { isHealth, sauriHealth } from "./test-backend";
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
let alarm: (value: { name: string }) => Promise<void>;

type FetchHandler = (url: string, init?: RequestInit) => Promise<Response>;

const bearerOf = (init?: RequestInit) => (init?.headers as Record<string, string> | undefined)?.Authorization;

async function boot(initialSession: Record<string, unknown>, initialLocal: Record<string, unknown> = {}, handler?: FetchHandler) {
  vi.resetModules();
  globalThis.indexedDB = new IDBFactory();
  globalThis.IDBKeyRange = IDBKeyRange;
  session = { sauriState: { status: "idle" }, ...initialSession };
  local = { ...initialLocal };
  const reply: FetchHandler = handler ?? (async () => uploaded.clone());
  // A reachable app answers discovery as Sauri; an offline one still throws.
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const response = await reply(url, init);
    return isHealth(url) && response.ok ? sauriHealth() : response;
  });
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
    alarms: { create: vi.fn(), onAlarm: { addListener: (fn: typeof alarm) => { alarm = fn; } } },
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
        remove: vi.fn(async (keys: string | string[]) => { for (const key of [keys].flat()) delete session[key]; }),
        setAccessLevel,
      },
      sync: { remove: syncRemove, set: syncSet, get: vi.fn() },
      local: {
        setAccessLevel,
        get: vi.fn(async (key: string) => (key in local ? { [key]: local[key] } : {})),
        set: vi.fn(async (values: Record<string, unknown>) => { Object.assign(local, values); }),
        remove: vi.fn(async (keys: string | string[]) => { localRemove(keys); for (const key of [keys].flat()) delete local[key]; }),
      },
    },
    tabs: { onRemoved: { addListener: vi.fn() }, onUpdated: { addListener: vi.fn() }, query: vi.fn(async () => []), create: vi.fn(async () => ({ id: 1 })), sendMessage: vi.fn(async () => undefined) },
  });
  await import("./background");
  listener({ type: "recording-stopped", size: 20, mimeType: "video/webm", sessionId: "synthetic-session" }, {}, vi.fn());
  await settle();
}

const ingestionCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/ingestion/upload"));

describe("service worker local pairing and offline queue", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, "log").mockImplementation(() => undefined);
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("queues a completed recording while the app is closed, retains it across alarms, then uploads automatically", async () => {
    let online = false;
    await boot({}, {}, async url => {
      if (!online) throw new TypeError("offline");
      if (url.endsWith("/pair")) return new Response(JSON.stringify({ token: "local-token" }));
      return uploaded.clone();
    });
    for (let attempt = 0; attempt < 5; attempt++) { await alarm({ name: "sauri-upload-check" }); await settle(); }
    expect(ingestionCalls()).toHaveLength(0);
    expect(await readJobs()).toEqual([expect.objectContaining({ status: "pending", retryCount: 0 })]);
    expect(clearSession).not.toHaveBeenCalled();
    online = true;
    await alarm({ name: "sauri-upload-check" });
    await vi.waitFor(async () => expect(await readJobs()).toEqual([expect.objectContaining({ status: "done", retryCount: 0 })]));
    await settle();
    expect(ingestionCalls()).toHaveLength(1);
    expect(bearerOf(ingestionCalls()[0][1])).toBe("Bearer local-token");
    expect(await readJobs()).toEqual([expect.objectContaining({ status: "done", retryCount: 0 })]);
    expect(clearSession).toHaveBeenCalledWith("synthetic-session");
  });

  it("uses the persisted local bearer and never old session credentials", async () => {
    await boot({ sauriSessionToken: "old" }, { sauriLocalToken: "local-token", sauriRefreshToken: "old", sauriSignInRequired: true, authToken: "old" });
    expect(bearerOf(ingestionCalls()[0][1])).toBe("Bearer local-token");
    expect(session.sauriSessionToken).toBeUndefined();
    expect(local).toEqual({ sauriLocalToken: "local-token" });
    expect(syncRemove).toHaveBeenCalledWith(expect.arrayContaining(["authToken"]));
    expect(setAccessLevel).toHaveBeenCalledWith({ accessLevel: "TRUSTED_CONTEXTS" });
    expect(syncSet).not.toHaveBeenCalled();
  });

  it.each([401, 403])("re-pairs once after upload status %s and keeps the same recording", async status => {
    await boot({}, { sauriLocalToken: "stale" }, async (url, init) => {
      if (url.endsWith("/pair")) return new Response(JSON.stringify({ token: "renewed" }));
      if (url.endsWith("/upload") && bearerOf(init) === "Bearer stale") return new Response("", { status });
      return uploaded.clone();
    });
    expect(ingestionCalls()).toHaveLength(2);
    expect(bearerOf(ingestionCalls()[1][1])).toBe("Bearer renewed");
    expect(await readJobs()).toEqual([expect.objectContaining({ status: "done", retryCount: 0 })]);
  });

  it("does not exhaust retries if the app disappears after health succeeds", async () => {
    await boot({}, { sauriLocalToken: "local-token" }, async url => {
      if (url.endsWith("/upload")) throw new TypeError("offline");
      return new Response("{}");
    });
    expect(ingestionCalls()).toHaveLength(1);
    expect(await readJobs()).toEqual([expect.objectContaining({ status: "pending", retryCount: 0 })]);
    expect(clearSession).not.toHaveBeenCalled();
  });
});
