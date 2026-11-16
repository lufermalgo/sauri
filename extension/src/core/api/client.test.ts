// API client integration tests (RED before implementation)
// Requirements: 13.1, 13.3, 13.4, 13.5, 14.1, 14.4, 14.5, 4.9, 6.6

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

/** Local (disk) storage of the last mock, where only the refresh token may live. */
let localStore: Record<string, unknown> = {};

function mockChromeStorage(initial: Record<string, unknown> = {}, initialLocal: Record<string, unknown> = {}) {
  const store: Record<string, unknown> = { ...initial };
  localStore = { ...initialLocal };
  const listeners: Array<(changes: unknown, area: string) => void> = [];
  (globalThis as unknown as { chrome: unknown }).chrome = {
    storage: {
      session: {
        get: vi.fn(async (key: string) => ({ [key]: store[key] })),
        set: vi.fn(async (obj: Record<string, unknown>) => {
          Object.assign(store, obj);
        }),
        remove: vi.fn(async (key: string) => {
          delete store[key];
        }),
      },
      local: {
        get: vi.fn(async (key: string) => (key in localStore ? { [key]: localStore[key] } : {})),
        set: vi.fn(async (obj: Record<string, unknown>) => { Object.assign(localStore, obj); }),
        remove: vi.fn(async (key: string) => { delete localStore[key]; }),
      },
      sync: { get: vi.fn(), set: vi.fn(), remove: vi.fn() },
      onChanged: { addListener: (fn: (c: unknown, a: string) => void) => listeners.push(fn) },
    },
  };
  return store;
}

describe("API client — authorization header and storage (Req. 13.1, 13.3, 14.1)", () => {
  beforeEach(() => {
    mockChromeStorage({ sauriSessionToken: "token-abc" });
    global.fetch = vi.fn(async () =>
      new Response(JSON.stringify([]), { status: 200 })
    ) as unknown as typeof fetch;
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it("attaches Authorization: Bearer {session} read from chrome.storage on every request", async () => {
    const { listMeetings } = await import("./client");
    await listMeetings("http://localhost:8000");
    expect(fetch).toHaveBeenCalled();
    const callArgs = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const init = callArgs[1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer token-abc");
  });
});

const bearer = (init?: RequestInit) => (init?.headers as Record<string, string> | undefined)?.Authorization;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

describe("API client — 401 handling (Req. 13.4)", () => {
  it("discards the stored session when the backend responds 401 and there is nothing to refresh", async () => {
    const store = mockChromeStorage({ sauriSessionToken: "expired-token" });
    global.fetch = vi.fn(async () => new Response("", { status: 401 })) as unknown as typeof fetch;

    const { listMeetings, InvalidSessionError } = await import("./client");
    await expect(listMeetings("http://localhost:8000")).rejects.toBeInstanceOf(InvalidSessionError);
    expect(store.sauriSessionToken).toBeUndefined();
    expect(fetch).toHaveBeenCalledTimes(1); // No refresh token: no refresh call, no retry.
  });
});

describe("API client — a stale 401 never signs the user out of a newer session (#1113)", () => {
  /** The server rejects only the expired token; the sign-in finishes while that request is in flight. */
  function lateUnauthorized(store: Record<string, unknown>, okResponse: () => Response) {
    global.fetch = vi.fn(async (_url: string, init?: RequestInit) => {
      if (bearer(init) === "Bearer fresh-token") return okResponse();
      store.sauriSessionToken = "fresh-token";
      return new Response("", { status: 401 });
    }) as unknown as typeof fetch;
  }

  it("keeps the fresh token and retries with it when a request sent with the expired one comes back 401", async () => {
    const store = mockChromeStorage({ sauriSessionToken: "expired-token" });
    lateUnauthorized(store, () => json([]));
    const { listMeetings } = await import("./client");
    await expect(listMeetings("http://localhost:8000")).resolves.toEqual([]);
    expect(store.sauriSessionToken).toBe("fresh-token");
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("/auth/refresh"))).toBe(false);
  });

  it("keeps the fresh token when a request sent with no token comes back 401", async () => {
    const store = mockChromeStorage({});
    lateUnauthorized(store, () => json([]));
    const { listMeetings } = await import("./client");
    await expect(listMeetings("http://localhost:8000")).resolves.toEqual([]);
    expect(store.sauriSessionToken).toBe("fresh-token");
  });

  it("applies the same rule when deleting a note", async () => {
    const store = mockChromeStorage({ sauriSessionToken: "expired-token" });
    lateUnauthorized(store, () => new Response(null, { status: 204 }));
    const { deleteMeeting } = await import("./client");
    await expect(deleteMeeting("m-1", "http://localhost:8000")).resolves.toBeUndefined();
    expect(store.sauriSessionToken).toBe("fresh-token");
  });
});

describe("API client — refresh token session", () => {
  const refreshUrl = (url: unknown) => String(url).endsWith("/api/v1/auth/refresh");
  const refreshCalls = () => vi.mocked(fetch).mock.calls.filter(([url]) => refreshUrl(url));
  const rotated = (n: number) => json({ access_token: `access-${n}`, refresh_token: `refresh-${n}`, expires_in: 3600, refresh_expires_in: 2592000 });
  afterEach(() => { vi.restoreAllMocks(); });

  it("silently signs in with the refresh token when no access token is left (after a restart)", async () => {
    const store = mockChromeStorage({}, { sauriRefreshToken: "refresh-1" });
    global.fetch = vi.fn(async (url: string, init?: RequestInit) =>
      refreshUrl(url) ? rotated(2) : bearer(init) === "Bearer access-2" ? json([]) : new Response("", { status: 401 })) as unknown as typeof fetch;
    const { listMeetings } = await import("./client");
    await expect(listMeetings("http://localhost:8000")).resolves.toEqual([]);
    expect(JSON.parse(String(refreshCalls()[0][1]?.body))).toEqual({ refresh_token: "refresh-1" });
    expect(store.sauriSessionToken).toBe("access-2");
    expect(localStore.sauriRefreshToken).toBe("refresh-2");
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(2); // The refresh and one authenticated call, never an unauthenticated one.
  });

  it("on a 401 refreshes once, stores the rotated tokens and retries the original request once", async () => {
    const store = mockChromeStorage({ sauriSessionToken: "expired-token" }, { sauriRefreshToken: "refresh-1" });
    global.fetch = vi.fn(async (url: string, init?: RequestInit) =>
      refreshUrl(url) ? rotated(2) : bearer(init) === "Bearer access-2" ? json([]) : new Response("", { status: 401 })) as unknown as typeof fetch;
    const { listMeetings } = await import("./client");
    await expect(listMeetings("http://localhost:8000")).resolves.toEqual([]);
    expect(vi.mocked(fetch).mock.calls.map(([url, init]) => [String(url).replace("http://localhost:8000", ""), bearer(init as RequestInit)])).toEqual([
      ["/api/v1/meetings/", "Bearer expired-token"],
      ["/api/v1/auth/refresh", undefined],
      ["/api/v1/meetings/", "Bearer access-2"],
    ]);
    expect(store.sauriSessionToken).toBe("access-2");
    expect(localStore.sauriRefreshToken).toBe("refresh-2");
  });

  it("a request that is still refused after a successful refresh is not retried again and ends the session", async () => {
    const store = mockChromeStorage({ sauriSessionToken: "expired-token" }, { sauriRefreshToken: "refresh-1" });
    global.fetch = vi.fn(async (url: string) => refreshUrl(url) ? rotated(2) : new Response("", { status: 401 })) as unknown as typeof fetch;
    const { listMeetings, InvalidSessionError } = await import("./client");
    await expect(listMeetings("http://localhost:8000")).rejects.toBeInstanceOf(InvalidSessionError);
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(3);
    expect(store.sauriSessionToken).toBeUndefined();
    expect(localStore.sauriRefreshToken).toBeUndefined();
  });

  it("when the refresh is refused it clears both credentials and reports an invalid session", async () => {
    const store = mockChromeStorage({ sauriSessionToken: "expired-token" }, { sauriRefreshToken: "refresh-1" });
    global.fetch = vi.fn(async () => new Response("{}", { status: 401 })) as unknown as typeof fetch;
    const { listMeetings, InvalidSessionError } = await import("./client");
    await expect(listMeetings("http://localhost:8000")).rejects.toBeInstanceOf(InvalidSessionError);
    expect(store.sauriSessionToken).toBeUndefined();
    expect(localStore.sauriRefreshToken).toBeUndefined();
    expect(refreshCalls()).toHaveLength(1);
  });

  it("when the server cannot be reached nothing is cleared and the error is not an invalid session", async () => {
    const store = mockChromeStorage({ sauriSessionToken: "expired-token" }, { sauriRefreshToken: "refresh-1" });
    global.fetch = vi.fn(async (url: string) => {
      if (refreshUrl(url)) throw new TypeError("offline");
      return new Response("", { status: 401 });
    }) as unknown as typeof fetch;
    const { listMeetings, InvalidSessionError } = await import("./client");
    const error = await listMeetings("http://localhost:8000").catch((reason: unknown) => reason);
    expect(error).toBeInstanceOf(Error);
    expect(error).not.toBeInstanceOf(InvalidSessionError);
    expect(store.sauriSessionToken).toBe("expired-token");
    expect(localStore.sauriRefreshToken).toBe("refresh-1");
  });

  it("a server error on refresh also keeps the credentials for a later attempt", async () => {
    mockChromeStorage({ sauriSessionToken: "expired-token" }, { sauriRefreshToken: "refresh-1" });
    global.fetch = vi.fn(async (url: string) => new Response("", { status: refreshUrl(url) ? 503 : 401 })) as unknown as typeof fetch;
    const { listMeetings } = await import("./client");
    await expect(listMeetings("http://localhost:8000")).rejects.toThrow("Session refresh unavailable");
    expect(localStore.sauriRefreshToken).toBe("refresh-1");
  });

  it("concurrent 401s share one refresh and every request is retried with the new token", async () => {
    mockChromeStorage({ sauriSessionToken: "expired-token" }, { sauriRefreshToken: "refresh-1" });
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    global.fetch = vi.fn(async (url: string, init?: RequestInit) => {
      if (refreshUrl(url)) { await gate; return rotated(2); }
      return bearer(init) === "Bearer access-2" ? json([]) : new Response("", { status: 401 });
    }) as unknown as typeof fetch;
    const { listMeetings, getMeeting } = await import("./client");
    const calls = [listMeetings("http://localhost:8000"), listMeetings("http://localhost:8000"), listMeetings("http://localhost:8000")];
    await vi.waitFor(() => expect(refreshCalls()).toHaveLength(1));
    release();
    await expect(Promise.all(calls)).resolves.toEqual([[], [], []]);
    expect(refreshCalls()).toHaveLength(1);
    // A late 401 from a slower request (sent before the refresh) finds the new token and does not refresh again.
    global.fetch = vi.fn(async (_url: string, init?: RequestInit) =>
      bearer(init) === "Bearer access-2" ? json({ meeting_id: "m", process_state: "completed" }) : new Response("", { status: 401 })) as unknown as typeof fetch;
    await expect(getMeeting("m", "http://localhost:8000")).resolves.toEqual({ meetingId: "m", processState: "completed" });
    expect(refreshCalls()).toHaveLength(0);
  });

  it("a refresh that finishes after a new sign-in is never needed: the new sign-in's tokens win", async () => {
    const store = mockChromeStorage({ sauriSessionToken: "expired-token" }, { sauriRefreshToken: "refresh-1" });
    global.fetch = vi.fn(async (url: string, init?: RequestInit) => {
      if (refreshUrl(url)) {
        // The user signed in again while the refresh was in flight, and the old family was refused.
        store.sauriSessionToken = "signed-in-access";
        localStore.sauriRefreshToken = "signed-in-refresh";
        return new Response("{}", { status: 401 });
      }
      return bearer(init) === "Bearer signed-in-access" ? json([]) : new Response("", { status: 401 });
    }) as unknown as typeof fetch;
    const { listMeetings, InvalidSessionError } = await import("./client");
    await expect(listMeetings("http://localhost:8000")).rejects.toBeInstanceOf(InvalidSessionError);
    expect(store.sauriSessionToken).toBe("signed-in-access");
    expect(localStore.sauriRefreshToken).toBe("signed-in-refresh");
  });

  it("login asks for a refreshable session and stores the access token in session and the refresh token in local storage only", async () => {
    const store = mockChromeStorage({}, { sauriRefreshToken: "stale-refresh" });
    global.fetch = vi.fn(async () => rotated(1)) as unknown as typeof fetch;
    const { login } = await import("./client");
    await login("a@b.c", "secret", "http://localhost:8000");
    expect(JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body))).toEqual({ email: "a@b.c", password: "secret", client: "extension" });
    expect(store.sauriSessionToken).toBe("access-1");
    expect(localStore.sauriRefreshToken).toBe("refresh-1");
    expect(JSON.stringify(store)).not.toContain("refresh-1");
    const chromeStorage = (globalThis as unknown as { chrome: { storage: { sync: { set: unknown } } } }).chrome.storage;
    expect(chromeStorage.sync.set).not.toHaveBeenCalled();
  });

  it("a login response without a refresh token (older backend) drops any stale refresh token", async () => {
    mockChromeStorage({}, { sauriRefreshToken: "stale-refresh" });
    global.fetch = vi.fn(async () => json({ access_token: "access-1", expires_in: 3600 })) as unknown as typeof fetch;
    const { login } = await import("./client");
    await login("a@b.c", "secret", "http://localhost:8000");
    expect(localStore.sauriRefreshToken).toBeUndefined();
  });

  it("sign-out clears both credentials first, then revokes the refresh family on the server", async () => {
    const store = mockChromeStorage({ sauriSessionToken: "access-1" }, { sauriRefreshToken: "refresh-1" });
    global.fetch = vi.fn(async () => {
      // By the time the server is called, nothing is left on this device.
      expect(store.sauriSessionToken).toBeUndefined();
      expect(localStore.sauriRefreshToken).toBeUndefined();
      return new Response(null, { status: 204 });
    }) as unknown as typeof fetch;
    const { signOut } = await import("./client");
    await signOut("http://localhost:8000");
    const [[url, init]] = vi.mocked(fetch).mock.calls;
    expect(String(url)).toBe("http://localhost:8000/api/v1/auth/refresh/revoke");
    expect(JSON.parse(String(init?.body))).toEqual({ refresh_token: "refresh-1" });
  });

  it("sign-out still signs out locally when the server is unreachable", async () => {
    const store = mockChromeStorage({ sauriSessionToken: "access-1" }, { sauriRefreshToken: "refresh-1" });
    global.fetch = vi.fn(async () => { throw new TypeError("offline"); }) as unknown as typeof fetch;
    const { signOut } = await import("./client");
    await expect(signOut("http://localhost:8000")).resolves.toBeUndefined();
    expect(store.sauriSessionToken).toBeUndefined();
    expect(localStore.sauriRefreshToken).toBeUndefined();
  });

  it("after a refresh, the pages' storage areas are untouched: nothing is written to sync, the token never reaches session", async () => {
    const store = mockChromeStorage({ sauriSessionToken: "expired-token" }, { sauriRefreshToken: "refresh-1" });
    global.fetch = vi.fn(async (url: string, init?: RequestInit) =>
      refreshUrl(url) ? rotated(2) : bearer(init) === "Bearer access-2" ? json([]) : new Response("", { status: 401 })) as unknown as typeof fetch;
    const { listMeetings } = await import("./client");
    await listMeetings("http://localhost:8000");
    const chromeStorage = (globalThis as unknown as { chrome: { storage: { sync: { set: unknown } } } }).chrome.storage;
    expect(chromeStorage.sync.set).not.toHaveBeenCalled();
    expect(Object.keys(store)).toEqual(["sauriSessionToken"]);
    expect(JSON.stringify(store)).not.toMatch(/refresh-/);
  });
});

describe("API client — timeout and retry (Req. 14.4, 14.5, 4.9, 6.6)", () => {
  beforeEach(() => {
    mockChromeStorage({ sauriSessionToken: "token-abc" });
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it("aborts the request after 10s via AbortController", async () => {
    vi.useFakeTimers();
    global.fetch = vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        })
    ) as unknown as typeof fetch;

    const { listMeetings } = await import("./client");
    const promise = listMeetings("http://localhost:8000");
    const expectation = expect(promise).rejects.toThrow();
    await vi.advanceTimersByTimeAsync(10_000);
    await expectation;
    vi.useRealTimers();
  });

  it("retrying re-issues the request", async () => {
    let calls = 0;
    global.fetch = vi.fn(async () => {
      calls += 1;
      return new Response(JSON.stringify([]), { status: 200 });
    }) as unknown as typeof fetch;

    const { listMeetings } = await import("./client");
    await listMeetings("http://localhost:8000");
    await listMeetings("http://localhost:8000");
    expect(calls).toBe(2);
  });
});

describe("API client — 404 distinguished from a real failure (Req. 7.6, 8.8, 10.5)", () => {
  beforeEach(() => {
    mockChromeStorage({ sauriSessionToken: "token-abc" });
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it("throws NotFoundError when the backend responds 404", async () => {
    global.fetch = vi.fn(async () => new Response("", { status: 404 })) as unknown as typeof fetch;
    const { getTranscript, NotFoundError } = await import("./client");
    await expect(getTranscript("r1", "http://localhost:8000")).rejects.toBeInstanceOf(NotFoundError);
  });
});

describe("API client — renameMeeting / deleteMeeting (My Notes → manage)", () => {
  beforeEach(() => {
    mockChromeStorage({ sauriSessionToken: "token-abc" });
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it("renameMeeting issues a PATCH with the new title in the body", async () => {
    global.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ meeting_id: "r1", title: "New title" }), { status: 200 })
    ) as unknown as typeof fetch;

    const { renameMeeting } = await import("./client");
    await renameMeeting("r1", "New title", "http://localhost:8000");

    expect(fetch).toHaveBeenCalled();
    const callArgs = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(callArgs[0]).toBe("http://localhost:8000/api/v1/meetings/r1");
    const init = callArgs[1] as RequestInit;
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({ title: "New title" });
  });

  it("renameMeeting throws NotFoundError on 404", async () => {
    global.fetch = vi.fn(async () => new Response("", { status: 404 })) as unknown as typeof fetch;
    const { renameMeeting, NotFoundError } = await import("./client");
    await expect(renameMeeting("r1", "X", "http://localhost:8000")).rejects.toBeInstanceOf(
      NotFoundError
    );
  });

  it("deleteMeeting issues a DELETE and doesn't fail parsing the bodyless 204", async () => {
    global.fetch = vi.fn(async () => new Response(null, { status: 204 })) as unknown as typeof fetch;
    const { deleteMeeting } = await import("./client");
    await expect(deleteMeeting("r1", "http://localhost:8000")).resolves.toBeUndefined();

    const callArgs = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(callArgs[0]).toBe("http://localhost:8000/api/v1/meetings/r1");
    const init = callArgs[1] as RequestInit;
    expect(init.method).toBe("DELETE");
  });

  it("deleteMeeting throws NotFoundError on 404", async () => {
    global.fetch = vi.fn(async () => new Response("", { status: 404 })) as unknown as typeof fetch;
    const { deleteMeeting, NotFoundError } = await import("./client");
    await expect(deleteMeeting("r1", "http://localhost:8000")).rejects.toBeInstanceOf(
      NotFoundError
    );
  });
});

describe("API client — encrypted transport (Req. 13.5)", () => {
  beforeEach(() => {
    mockChromeStorage({ sauriSessionToken: "token-abc" });
  });

  it("rejects a non-localhost http:// backendUrl", async () => {
    const { listMeetings } = await import("./client");
    await expect(listMeetings("http://api.sauri.example.com")).rejects.toThrow();
  });

  it("accepts http://localhost", async () => {
    global.fetch = vi.fn(async () => new Response(JSON.stringify([]), { status: 200 })) as unknown as typeof fetch;
    const { listMeetings } = await import("./client");
    await expect(listMeetings("http://localhost:8000")).resolves.toEqual([]);
  });

  it("accepts https:// in production", async () => {
    global.fetch = vi.fn(async () => new Response(JSON.stringify([]), { status: 200 })) as unknown as typeof fetch;
    const { listMeetings } = await import("./client");
    await expect(listMeetings("https://api.sauri.example.com")).resolves.toEqual([]);
  });
});

describe("API client — validateTransport policy", () => {
  it.each([
    "https://api.sauri.example.com",
    "https://localhost:8443",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
  ])("allows %s", async (url) => {
    const { validateTransport } = await import("./client");
    expect(() => validateTransport(url)).not.toThrow();
  });

  it.each([
    "http://api.sauri.example.com",
    "http://localhost.evil.example",
    "http://127.0.0.1.evil.example",
    "http://evil.example/localhost",
    "http://192.168.1.10:8000",
    "http://[::1]:8000",
    "ftp://localhost",
    "ws://localhost:8000",
  ])("rejects %s", async (url) => {
    const { validateTransport, InsecureTransportError } = await import("./client");
    expect(() => validateTransport(url)).toThrow(InsecureTransportError);
  });

  it("never sends the token (or credentials) over an insecure backend URL", async () => {
    mockChromeStorage({ sauriSessionToken: "token-abc" });
    global.fetch = vi.fn(async () => new Response("[]", { status: 200 })) as unknown as typeof fetch;
    const { listMeetings, login, deleteMeeting } = await import("./client");
    await expect(listMeetings("http://api.sauri.example.com")).rejects.toThrow();
    await expect(deleteMeeting("m1", "http://api.sauri.example.com")).rejects.toThrow();
    await expect(login("a@b.c", "secret", "http://api.sauri.example.com")).rejects.toThrow();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("stores the token returned by login in session storage only", async () => {
    const store = mockChromeStorage();
    global.fetch = vi.fn(async () => new Response(JSON.stringify({ access_token: "new-token", expires_in: 3600 }), { status: 200 })) as unknown as typeof fetch;
    const { login } = await import("./client");
    await login("a@b.c", "secret", "http://localhost:8000");
    expect(store.sauriSessionToken).toBe("new-token");
    expect(localStore).toEqual({});
  });
});
