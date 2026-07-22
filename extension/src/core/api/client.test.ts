// API client integration tests (RED before implementation)
// Requirements: 13.1, 13.3, 13.4, 13.5, 14.1, 14.4, 14.5, 4.9, 6.6

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

function mockChromeStorage(initial: Record<string, unknown> = {}) {
  const store: Record<string, unknown> = { ...initial };
  const listeners: Array<(changes: unknown, area: string) => void> = [];
  (globalThis as unknown as { chrome: unknown }).chrome = {
    storage: {
      sync: {
        get: vi.fn(async (key: string) => ({ [key]: store[key] })),
        set: vi.fn(async (obj: Record<string, unknown>) => {
          Object.assign(store, obj);
        }),
        remove: vi.fn(async (key: string) => {
          delete store[key];
        }),
      },
      onChanged: { addListener: (fn: (c: unknown, a: string) => void) => listeners.push(fn) },
    },
  };
  return store;
}

describe("API client — authorization header and storage (Req. 13.1, 13.3, 14.1)", () => {
  beforeEach(() => {
    mockChromeStorage({ authToken: "token-abc" });
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

describe("API client — 401 handling (Req. 13.4)", () => {
  it("discards the stored session when the backend responds 401", async () => {
    const store = mockChromeStorage({ authToken: "expired-token" });
    global.fetch = vi.fn(async () => new Response("", { status: 401 })) as unknown as typeof fetch;

    const { listMeetings } = await import("./client");
    await expect(listMeetings("http://localhost:8000")).rejects.toThrow();
    expect(store.authToken).toBeUndefined();
  });
});

describe("API client — timeout and retry (Req. 14.4, 14.5, 4.9, 6.6)", () => {
  beforeEach(() => {
    mockChromeStorage({ authToken: "token-abc" });
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
    mockChromeStorage({ authToken: "token-abc" });
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
    mockChromeStorage({ authToken: "token-abc" });
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
    mockChromeStorage({ authToken: "token-abc" });
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
