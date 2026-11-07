// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "./App";

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

    await waitFor(() => expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy());
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

    expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Meetings" })).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "owner@example.test" },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "synthetic-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: /log in/i }));

    await waitFor(() => expect(screen.getByText("No meetings registered.")).toBeTruthy());
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual([
      expect.stringContaining("/api/v1/auth/login"),
      expect.stringContaining("/api/v1/meetings"),
    ]);
  });
});
