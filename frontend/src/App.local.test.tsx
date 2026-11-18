// @vitest-environment jsdom
// @vitest-environment-options {"url":"http://localhost:8000/"}
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { App } from "./App";
import { detectLocalSession } from "./api";
import { t } from "./i18n";
import { createMemoryStorage } from "./test/storage";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function localApi() {
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    expect(new Headers(init?.headers).has("Authorization")).toBe(false);
    const path = String(input);
    if (path.endsWith("/local/status")) return json({ mode: "local", ready: true, processing: 0, version: "test" });
    if (path.endsWith("/local/me")) return json({ name: "Local Tester", email: "local@sauri.local" });
    if (path.endsWith("/meetings")) return json([]);
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

beforeEach(() => {
  vi.stubGlobal("localStorage", createMemoryStorage());
  window.history.replaceState({}, "", "/");
});

afterEach(async () => {
  cleanup();
  vi.stubGlobal("fetch", vi.fn(async () => json({}, 404)));
  await detectLocalSession();
  vi.unstubAllGlobals();
});

describe("same-origin local session", () => {
  it.each([null, "stale-password-token"])("opens the library with no login flash and token %s", async (token) => {
    if (token) localStorage.setItem("sauri_token", token);
    localStorage.setItem("sauri_last_meeting_id", "previous-meeting");
    const fetch = localApi();
    render(<App />);
    expect(screen.queryByLabelText(t("login:emailLabel"))).toBeNull();
    expect(await screen.findByText(t("library:empty"))).toBeTruthy();
    expect(screen.getByText("Local Tester")).toBeTruthy();
    expect(window.location.pathname).toBe("/");
    expect(fetch.mock.calls.map(([input]) => String(input))).toEqual([
      "http://localhost:8000/api/v1/local/status",
      "http://localhost:8000/api/v1/local/me",
      "http://localhost:8000/api/v1/meetings",
    ]);
    act(() => window.dispatchEvent(new Event("sauri:unauthorized")));
    expect(screen.queryByLabelText(t("login:emailLabel"))).toBeNull();
  });

  it("shows the real name in account settings without a sidebar or account sign-out", async () => {
    window.history.replaceState({}, "", "/settings/cuenta");
    localApi();
    render(<App />);
    expect(await screen.findByText(t("settings:account.localNote"))).toBeTruthy();
    expect(screen.getAllByText("Local Tester").length).toBeGreaterThan(0);
    expect(screen.queryByText(t("shell:logout"))).toBeNull();
    expect(screen.queryByText(t("settings:account.sessionHelp"))).toBeNull();
    expect(screen.queryByRole("button", { name: /Local Tester/ })).toBeNull();
  });

  it("preserves password login when status explicitly returns 404", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({}, 404)));
    render(<App />);
    expect(await screen.findByLabelText(t("login:emailLabel"))).toBeTruthy();
  });

  it("does not turn a local API failure into a login prompt, and retries", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "local_user_missing" }, 500)));
    render(<App />);
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByLabelText(t("login:emailLabel"))).toBeNull();
    localApi();
    fireEvent.click(screen.getByRole("button", { name: t("shell:localSession.retry") }));
    expect(await screen.findByText(t("library:empty"))).toBeTruthy();
  });
});
