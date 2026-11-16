// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "./App";
import { copy } from "./copy/es";

function createLocalStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, String(value)),
  };
}

afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/");
  vi.unstubAllGlobals();
});

describe("global authentication gate", () => {
  it("returns to login when a protected API request rejects the stored token", async () => {
    const storage = createLocalStorage();
    storage.setItem("sauri_token", "synthetic-expired-token");
    vi.stubGlobal("localStorage", storage);
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/meetings")) {
        return new Response(JSON.stringify({ detail: "Unauthorized" }), { status: 401 });
      }
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await waitFor(() => expect(screen.getByRole("heading", { name: copy.login.title })).toBeTruthy());
    expect(storage.getItem("sauri_token")).toBeNull();
    expect(screen.queryByText("Error 401")).toBeNull();
  });

  it("does not mount API-backed app screens until login succeeds", async () => {
    vi.stubGlobal("localStorage", createLocalStorage());
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/auth/login")) {
        return new Response(JSON.stringify({
          access_token: "synthetic-access-token",
          token_type: "bearer",
          expires_in: 3600,
        }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(screen.getByRole("heading", { name: copy.login.title })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: copy.library.title })).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(copy.login.emailLabel), {
      target: { value: "owner@example.test" },
    });
    fireEvent.change(screen.getByLabelText(copy.login.passwordLabel), {
      target: { value: "synthetic-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: copy.login.submit }));

    await waitFor(() => expect(screen.getByText(copy.library.empty)).toBeTruthy());
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual([
      expect.stringContaining("/api/v1/auth/login"),
      expect.stringContaining("/api/v1/meetings"),
    ]);
  });

  it("shows the shell with a library link for an unknown route", () => {
    window.history.replaceState({}, "", "/nowhere");
    const storage = createLocalStorage();
    storage.setItem("sauri_token", "synthetic-token");
    vi.stubGlobal("localStorage", storage);
    vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200 })));

    render(<App />);

    expect(screen.getByRole("heading", { name: copy.shell.notFound.title })).toBeTruthy();
    fireEvent.click(screen.getByRole("link", { name: copy.shell.notFound.backToLibrary }));
    expect(window.location.pathname).toBe("/");
  });

  it("opens the settings page from the gear and keeps unknown nearby paths not found", async () => {
    const storage = createLocalStorage();
    storage.setItem("sauri_token", "synthetic-token");
    vi.stubGlobal("localStorage", storage);
    vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200 })));

    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: copy.shell.profile.settings }));

    await waitFor(() => expect(window.location.pathname).toBe("/settings"));
    expect(screen.getByRole("heading", { name: copy.settings.title })).toBeTruthy();
    expect(screen.getByRole("heading", { name: copy.settings.categories.account.label })).toBeTruthy();
    expect(screen.getByRole("link", { name: copy.shell.profile.settings }).getAttribute("aria-current")).toBe("page");

    act(() => {
      window.history.pushState(null, "", "/settings/extra");
      window.dispatchEvent(new Event("sauri:navigate"));
    });
    expect(screen.getByRole("heading", { name: copy.shell.notFound.title })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: copy.settings.title })).toBeNull();
  });

  it("shows the name and email carried by the signed-in token", () => {
    const payload = btoa(JSON.stringify({ name: "Synthetic Owner", email: "owner@example.test" }));
    const storage = createLocalStorage();
    storage.setItem("sauri_token", `header.${payload}.signature`);
    vi.stubGlobal("localStorage", storage);
    vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200 })));

    render(<App />);

    expect(screen.getByText("Synthetic Owner")).toBeTruthy();
    expect(screen.getByText("owner@example.test")).toBeTruthy();
  });

  it("logs out to the library route and removes only the token", async () => {
    window.history.replaceState({}, "", "/upload");
    const storage = createLocalStorage();
    storage.setItem("sauri_token", "synthetic-token");
    vi.stubGlobal("localStorage", storage);

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: copy.shell.profile.fallbackName }));
    fireEvent.click(screen.getByRole("menuitem", { name: copy.shell.logout }));

    await waitFor(() => expect(screen.getByRole("heading", { name: copy.login.title })).toBeTruthy());
    expect(storage.getItem("sauri_token")).toBeNull();
    expect(window.location.pathname).toBe("/");
  });

  it("navigates with the browser back button between routes", async () => {
    const storage = createLocalStorage();
    storage.setItem("sauri_token", "synthetic-token");
    vi.stubGlobal("localStorage", storage);
    vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200 })));

    render(<App />);
    fireEvent.click(screen.getAllByRole("button", { name: copy.shell.upload })[0]);
    await waitFor(() => expect(window.location.pathname).toBe("/upload"));
    expect(screen.getByRole("link", { name: copy.shell.library }).getAttribute("aria-current")).toBeNull();

    window.history.back();
    await waitFor(() => expect(window.location.pathname).toBe("/"));
    await waitFor(() =>
      expect(screen.getByRole("link", { name: copy.shell.library }).getAttribute("aria-current")).toBe("page"));
  });
});
