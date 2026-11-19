// API client integration tests (RED before implementation)
// Requirements: 13.1, 13.3, 13.4, 13.5, 14.1, 14.4, 14.5, 4.9, 6.6

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

/** Local (disk) storage of the last mock, where the local pairing token lives. */
let localStore: Record<string, unknown> = {};

function mockChromeStorage(initial: Record<string, unknown> = {}, initialLocal: Record<string, unknown> = {}) {
  // The app was found on the desktop port earlier in this browser session.
  const store: Record<string, unknown> = { sauriBackendUrl: "http://localhost:41750", ...initial };
  localStore = { ...initial, ...initialLocal };
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
        setAccessLevel: vi.fn(async () => {}),
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
    mockChromeStorage({ sauriLocalToken: "token-abc" });
    global.fetch = vi.fn(async () =>
      new Response(JSON.stringify([]), { status: 200 })
    ) as unknown as typeof fetch;
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it("attaches Authorization: Bearer {local token} read from chrome.storage on every request", async () => {
    const { listMeetings } = await import("./client");
    await listMeetings();
    expect(fetch).toHaveBeenCalled();
    const callArgs = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const init = callArgs[1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer token-abc");
  });
});

const bearer = (init?: RequestInit) => (init?.headers as Record<string, string> | undefined)?.Authorization;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

describe("API client — timeout and retry (Req. 14.4, 14.5, 4.9, 6.6)", () => {
  beforeEach(() => {
    mockChromeStorage({ sauriLocalToken: "token-abc" });
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
    const promise = listMeetings();
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
    await listMeetings();
    await listMeetings();
    expect(calls).toBe(2);
  });
});

describe("API client — 404 distinguished from a real failure (Req. 7.6, 8.8, 10.5)", () => {
  beforeEach(() => {
    mockChromeStorage({ sauriLocalToken: "token-abc" });
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it("throws NotFoundError when the backend responds 404", async () => {
    global.fetch = vi.fn(async () => new Response("", { status: 404 })) as unknown as typeof fetch;
    const { getTranscript, NotFoundError } = await import("./client");
    await expect(getTranscript("r1")).rejects.toBeInstanceOf(NotFoundError);
  });
});

describe("API client — renameMeeting / deleteMeeting (My Notes → manage)", () => {
  beforeEach(() => {
    mockChromeStorage({ sauriLocalToken: "token-abc" });
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it("renameMeeting issues a PATCH with the new title in the body", async () => {
    global.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ meeting_id: "r1", title: "New title" }), { status: 200 })
    ) as unknown as typeof fetch;

    const { renameMeeting } = await import("./client");
    await renameMeeting("r1", "New title");

    expect(fetch).toHaveBeenCalled();
    const callArgs = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(callArgs[0]).toBe("http://localhost:41750/api/v1/meetings/r1");
    const init = callArgs[1] as RequestInit;
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({ title: "New title" });
  });

  it("renameMeeting throws NotFoundError on 404", async () => {
    global.fetch = vi.fn(async () => new Response("", { status: 404 })) as unknown as typeof fetch;
    const { renameMeeting, NotFoundError } = await import("./client");
    await expect(renameMeeting("r1", "X")).rejects.toBeInstanceOf(
      NotFoundError
    );
  });

  it("deleteMeeting issues a DELETE and doesn't fail parsing the bodyless 204", async () => {
    global.fetch = vi.fn(async () => new Response(null, { status: 204 })) as unknown as typeof fetch;
    const { deleteMeeting } = await import("./client");
    await expect(deleteMeeting("r1")).resolves.toBeUndefined();

    const callArgs = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(callArgs[0]).toBe("http://localhost:41750/api/v1/meetings/r1");
    const init = callArgs[1] as RequestInit;
    expect(init.method).toBe("DELETE");
  });

  it("deleteMeeting throws NotFoundError on 404", async () => {
    global.fetch = vi.fn(async () => new Response("", { status: 404 })) as unknown as typeof fetch;
    const { deleteMeeting, NotFoundError } = await import("./client");
    await expect(deleteMeeting("r1")).rejects.toBeInstanceOf(
      NotFoundError
    );
  });
});

describe("API client — encrypted transport (Req. 13.5)", () => {
  beforeEach(() => {
    mockChromeStorage({ sauriLocalToken: "token-abc" });
  });

  it("accepts http://localhost", async () => {
    global.fetch = vi.fn(async () => new Response(JSON.stringify([]), { status: 200 })) as unknown as typeof fetch;
    const { listMeetings } = await import("./client");
    await expect(listMeetings()).resolves.toEqual([]);
  });

  it("ignores a remembered address that is not one of the fixed local candidates", async () => {
    vi.resetModules();
    mockChromeStorage({ sauriLocalToken: "token-abc", sauriBackendUrl: "https://api.sauri.example.com" });
    global.fetch = vi.fn(async () => new Response(JSON.stringify([]), { status: 200 })) as unknown as typeof fetch;
    const { listMeetings } = await import("./client");
    // No candidate answers as Sauri, so nothing is sent with the credential.
    await expect(listMeetings()).rejects.toThrow("Local app unavailable");
    const urls = vi.mocked(fetch).mock.calls.map(([url]) => String(url));
    expect(urls).toEqual(["http://localhost:41750/health", "http://localhost:8000/health"]);
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

});
