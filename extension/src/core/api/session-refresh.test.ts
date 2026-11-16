// Refresh coordination across extension contexts (service worker, side panel, options page).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let session: Record<string, unknown>;
let local: Record<string, unknown>;
let refreshCalls: number;

/** A minimal Web Locks double: one holder at a time per name, shared by every module instance. */
function fakeLocks() {
  let tail: Promise<unknown> = Promise.resolve();
  return {
    request: vi.fn((_name: string, work: () => Promise<unknown>) => {
      const run = tail.then(work, work);
      tail = run.catch(() => undefined);
      return run;
    }),
  };
}

beforeEach(() => {
  session = { sauriSessionToken: "expired-token" };
  local = { sauriRefreshToken: "refresh-1" };
  refreshCalls = 0;
  vi.stubGlobal("chrome", {
    storage: {
      session: {
        get: vi.fn(async (key: string) => (key in session ? { [key]: session[key] } : {})),
        set: vi.fn(async (values: Record<string, unknown>) => { Object.assign(session, values); }),
        remove: vi.fn(async (key: string) => { delete session[key]; }),
      },
      local: {
        get: vi.fn(async (key: string) => (key in local ? { [key]: local[key] } : {})),
        set: vi.fn(async (values: Record<string, unknown>) => { Object.assign(local, values); }),
        remove: vi.fn(async (key: string) => { delete local[key]; }),
      },
    },
  });
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
    refreshCalls += 1;
    // The server retires the token it is given: presenting "refresh-1" twice would revoke the family.
    const presented = JSON.parse(String(init?.body)).refresh_token;
    if (presented !== "refresh-1") return new Response("{}", { status: 401 });
    await new Promise((resolve) => setTimeout(resolve, 5));
    return new Response(JSON.stringify({ access_token: "access-2", refresh_token: "refresh-2" }), { status: 200 });
  }));
});
afterEach(() => { vi.unstubAllGlobals(); vi.resetModules(); });

describe("refresh coordination across contexts", () => {
  it("runs the exchange under the shared Web Lock", async () => {
    const locks = fakeLocks();
    vi.stubGlobal("navigator", { locks });
    const { refreshAccessToken } = await import("./session-refresh");
    await expect(refreshAccessToken("http://localhost:8000", "expired-token")).resolves.toEqual({ status: "ok", accessToken: "access-2" });
    expect(locks.request).toHaveBeenCalledWith("sauri-session-refresh", expect.any(Function));
  });

  it("two contexts that both saw the 401 refresh only once: the second finds the new access token", async () => {
    vi.stubGlobal("navigator", { locks: fakeLocks() });
    const contextA = await import("./session-refresh");
    vi.resetModules(); // A separate module instance has its own in-memory state, like another extension page.
    const contextB = await import("./session-refresh");
    expect(contextA.refreshAccessToken).not.toBe(contextB.refreshAccessToken);
    const outcomes = await Promise.all([
      contextA.refreshAccessToken("http://localhost:8000", "expired-token"),
      contextB.refreshAccessToken("http://localhost:8000", "expired-token"),
    ]);
    expect(outcomes).toEqual([{ status: "ok", accessToken: "access-2" }, { status: "ok", accessToken: "access-2" }]);
    expect(refreshCalls).toBe(1);
    expect(local.sauriRefreshToken).toBe("refresh-2");
  });

  it("still works where Web Locks are unavailable, deduplicating within the context", async () => {
    vi.stubGlobal("navigator", {});
    const { refreshAccessToken } = await import("./session-refresh");
    const outcomes = await Promise.all([
      refreshAccessToken("http://localhost:8000", "expired-token"),
      refreshAccessToken("http://localhost:8000", "expired-token"),
    ]);
    expect(outcomes.every((outcome) => outcome.status === "ok")).toBe(true);
    expect(refreshCalls).toBe(1);
  });

  it("a rejected refresh clears both credentials and a later call makes no server request", async () => {
    local.sauriRefreshToken = "revoked-refresh";
    vi.stubGlobal("navigator", { locks: fakeLocks() });
    const { refreshAccessToken, ensureAccessToken } = await import("./session-refresh");
    await expect(refreshAccessToken("http://localhost:8000", "expired-token")).resolves.toEqual({ status: "rejected" });
    expect(session.sauriSessionToken).toBeUndefined();
    expect(local.sauriRefreshToken).toBeUndefined();
    await expect(ensureAccessToken("http://localhost:8000")).resolves.toEqual({ status: "rejected" });
    expect(refreshCalls).toBe(1);
  });

  it("a response missing either token is treated as unavailable and stores nothing", async () => {
    vi.stubGlobal("navigator", {});
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ access_token: "access-2" }), { status: 200 })));
    const { refreshAccessToken } = await import("./session-refresh");
    await expect(refreshAccessToken("http://localhost:8000", "expired-token")).resolves.toEqual({ status: "unavailable" });
    expect(session.sauriSessionToken).toBe("expired-token");
    expect(local.sauriRefreshToken).toBe("refresh-1");
  });

  it("refuses an insecure backend before sending anything", async () => {
    vi.stubGlobal("navigator", {});
    const { refreshAccessToken } = await import("./session-refresh");
    await expect(refreshAccessToken("http://api.sauri.example.com", "expired-token")).rejects.toThrow();
    expect(refreshCalls).toBe(0);
  });
});
