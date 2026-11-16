// @vitest-environment jsdom
/**
 * The portal reopens the recording the user last explored, once per start and only from `/`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "./App";
import { navigate } from "./router";
import { t } from "./i18n";

const KEY = "sauri_last_meeting_id";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function listItem(id: string, title: string) {
  return {
    meeting_id: id, meet_link: null, origin: "manual", process_state: "completed", failure_cause: null,
    created_at: "2026-10-28T17:45:00Z", title, duration_seconds: 600, speaker_count: 2, summary_topic: null,
    thumbnail_url: null, media_kind: "video",
  };
}

/** A fake API: `known` are the recordings the server still has; `listed` the ones its list returns. */
function stubApi(known: string[], listed: string[] = known) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL(String(input), "http://localhost").pathname;
    if (path.endsWith("/auth/login")) return json({ access_token: "synthetic-token", token_type: "bearer", expires_in: 3600 });
    if (path.endsWith("/api/v1/meetings")) return json(listed.map((id) => listItem(id, `Recording ${id}`)));
    const match = /\/api\/v1\/meetings\/([^/]+)(\/.*)?$/.exec(path);
    if (!match) return json({}, 404);
    const [, id, rest] = match;
    if (!known.includes(id)) return json({ detail: "Not found" }, 404);
    if (!rest) return json({ meeting_id: id, process_state: "completed" });
    if (rest === "/diarization") return json({ speakers: [], assignments: [] });
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function createLocalStorage(initial: Record<string, string> = { sauri_token: "synthetic-token" }): Storage {
  const values = new Map(Object.entries(initial));
  return {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, String(value)),
  };
}

function stubViewport(width: number) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: (() => {
      const min = /min-width:\s*(\d+)/.exec(query);
      const max = /max-width:\s*(\d+)/.exec(query);
      return (min ? width >= Number(min[1]) : true) && (max ? width <= Number(max[1]) : true);
    })(),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

const heading = (id: string) => screen.findByRole("heading", { level: 1, name: `Recording ${id}` });

beforeEach(() => {
  stubViewport(1440);
  vi.stubGlobal("localStorage", createLocalStorage());
  window.history.replaceState(null, "", "/");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

describe("remembering the recording", () => {
  it("stores the id of a recording once it has loaded", async () => {
    stubApi(["a", "b"]);
    window.history.replaceState(null, "", "/meetings/b");
    render(<App />);
    await heading("b");
    expect(localStorage.getItem(KEY)).toBe("b");
  });

  it("does not store the id of a recording the server does not know", async () => {
    stubApi(["a"]);
    window.history.replaceState(null, "", "/meetings/ghost");
    render(<App />);
    await screen.findByRole("region", { name: t("library:title") });
    await waitFor(() => expect(localStorage.getItem(KEY)).toBeNull());
  });

  it("follows the recording the user opens from the list", async () => {
    stubApi(["a", "b"]);
    localStorage.setItem(KEY, "a");
    render(<App />);
    await heading("a");
    act(() => navigate({ name: "meeting", meetingId: "b" }));
    await heading("b");
    expect(localStorage.getItem(KEY)).toBe("b");
  });
});

describe("reopening at start", () => {
  it("replaces / with the last recording before the first paint, without adding a history entry", async () => {
    stubApi(["a", "b"]);
    localStorage.setItem(KEY, "b");
    const entries = window.history.length;
    const replace = vi.spyOn(window.history, "replaceState");
    const push = vi.spyOn(window.history, "pushState");
    render(<App />);
    // Synchronously after the first render: already on the recording, never on the empty library.
    expect(window.location.pathname).toBe("/meetings/b");
    expect(screen.queryByText(t("library:selectHint"))).toBeNull();
    expect(replace).toHaveBeenCalledWith(null, "", "/meetings/b");
    expect(push).not.toHaveBeenCalled();
    expect(window.history.length).toBe(entries);
    await heading("b");
  });

  it("does not redirect again when the user returns to / during the session", async () => {
    stubApi(["a", "b"]);
    localStorage.setItem(KEY, "b");
    render(<App />);
    await heading("b");
    act(() => navigate({ name: "library" }));
    expect(window.location.pathname).toBe("/");
    expect(await screen.findByText(t("library:selectHint"))).toBeVisible();
    // The browser's Back and Forward through / do not redirect either.
    window.history.back();
    await waitFor(() => expect(window.location.pathname).not.toBe("/meetings/b"));
    expect(screen.queryByRole("heading", { name: "Recording b" })).toBeNull();
  });

  it("does not trap Back: the replaced entry is the only one for the start", async () => {
    stubApi(["a"]);
    localStorage.setItem(KEY, "a");
    window.history.pushState(null, "", "/");
    window.history.replaceState(null, "", "/");
    const entries = window.history.length;
    render(<App />);
    await heading("a");
    expect(window.history.length).toBe(entries);
  });

  it("starts at the library when nothing was explored yet", async () => {
    stubApi(["a"]);
    render(<App />);
    expect(await screen.findByText(t("library:selectHint"))).toBeVisible();
    expect(window.location.pathname).toBe("/");
  });

  it.each(["/meetings/a", "/upload", "/settings/apariencia"])("leaves a direct link to %s alone", async (path) => {
    stubApi(["a", "b"]);
    localStorage.setItem(KEY, "b");
    window.history.replaceState(null, "", path);
    render(<App />);
    await screen.findByRole("navigation", { name: t("shell:navLabel") });
    expect(window.location.pathname).toBe(path);
    act(() => navigate({ name: "library" }));
    expect(window.location.pathname).toBe("/");
    expect(screen.queryByRole("heading", { name: "Recording b" })).toBeNull();
  });

  it("restores the last recording after login", async () => {
    stubApi(["a"]);
    vi.stubGlobal("localStorage", createLocalStorage({ [KEY]: "a" }));
    render(<App />);
    expect(screen.getByRole("heading", { name: `${t("login:titleLead")} ${t("shell:brand")}` })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(t("login:emailLabel")), { target: { value: "owner@example.test" } });
    fireEvent.change(screen.getByLabelText(t("login:passwordLabel")), { target: { value: "synthetic-password" } });
    fireEvent.click(screen.getByRole("button", { name: t("login:submit") }));
    await heading("a");
    expect(window.location.pathname).toBe("/meetings/a");
  });

  it("keeps working, without redirecting, when storage cannot be read", async () => {
    stubApi(["a"]);
    const blocked = () => { throw new DOMException("blocked", "SecurityError"); };
    const storage = createLocalStorage();
    vi.stubGlobal("localStorage", { ...storage, getItem: (key: string) => (key === "sauri_token" ? "synthetic-token" : blocked()), setItem: blocked, removeItem: blocked });
    render(<App />);
    expect(await screen.findByText(t("library:selectHint"))).toBeVisible();
    expect(window.location.pathname).toBe("/");
    act(() => navigate({ name: "meeting", meetingId: "a" }));
    await heading("a");
  });
});

describe("a recording that is gone", () => {
  it("clears the key and shows the library when the server no longer has it", async () => {
    stubApi(["a"], ["a"]);
    localStorage.setItem(KEY, "gone");
    render(<App />);
    await waitFor(() => expect(window.location.pathname).toBe("/"));
    expect(localStorage.getItem(KEY)).toBeNull();
    expect(await screen.findByText(t("library:selectHint"))).toBeVisible();
    expect(screen.getByRole("heading", { level: 1, name: t("library:title") })).toBeVisible();
  });

  it("clears the key and shows the library when the list no longer has it", async () => {
    stubApi(["a", "gone"], ["a"]);
    localStorage.setItem(KEY, "gone");
    render(<App />);
    await waitFor(() => expect(window.location.pathname).toBe("/"));
    await waitFor(() => expect(localStorage.getItem(KEY)).toBeNull());
    expect(await screen.findByText(t("library:selectHint"))).toBeVisible();
  });

  it("does not redirect away from a deep link to a missing recording, but forgets it", async () => {
    stubApi(["a"]);
    localStorage.setItem(KEY, "gone");
    window.history.replaceState(null, "", "/meetings/gone");
    render(<App />);
    await waitFor(() => expect(localStorage.getItem(KEY)).toBeNull());
    expect(window.location.pathname).toBe("/meetings/gone");
  });
});

describe("Biblioteca from another section", () => {
  beforeEach(() => { stubApi(["a"]); });

  it("goes to the last recording when there is one", async () => {
    localStorage.setItem(KEY, "a");
    window.history.replaceState(null, "", "/settings/apariencia");
    render(<App />);
    const link = await screen.findByRole("link", { name: t("shell:library") });
    expect(link).toHaveAttribute("href", "/meetings/a");
    fireEvent.click(link);
    expect(window.location.pathname).toBe("/meetings/a");
    await heading("a");
  });

  it("goes to the library when nothing was explored", async () => {
    window.history.replaceState(null, "", "/settings/apariencia");
    render(<App />);
    const link = await screen.findByRole("link", { name: t("shell:library") });
    expect(link).toHaveAttribute("href", "/");
    fireEvent.click(link);
    expect(window.location.pathname).toBe("/");
  });
});
