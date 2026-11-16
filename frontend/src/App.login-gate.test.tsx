// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "./App";
import * as api from "./api";
import { t } from "./i18n";

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return { ...actual, login: vi.fn(), uploadRecording: vi.fn() };
});
vi.mock("./components/RecordingLibrary", () => ({
  RecordingLibrary: () => <div>Meeting list</div>,
}));
vi.mock("./components/TranscriptView", () => ({
  TranscriptView: () => <div>Transcript</div>,
}));

const credentials = { email: "owner@example.test", password: "synthetic-password" };

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

function openPortal() {
  localStorage.setItem("sauri_token", "synthetic-existing-token");
  render(<App />);
}

function enterCredentials() {
  fireEvent.change(screen.getByLabelText(t("login:emailLabel")), { target: { value: credentials.email } });
  fireEvent.change(screen.getByLabelText(t("login:passwordLabel")), { target: { value: credentials.password } });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.stubGlobal("localStorage", createLocalStorage());
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("login and local session gate", () => {
  it("shows login before mounting the authenticated app when no token exists", () => {
    render(<App />);

    expect(screen.getByLabelText(t("login:emailLabel"))).toBeTruthy();
    expect(screen.getByLabelText(t("login:passwordLabel"))).toBeTruthy();
    expect(screen.getByRole("button", { name: t("login:submit") })).toBeTruthy();
  });

  it("keeps the portal hidden while login is pending and prevents duplicate submission", async () => {
    const pendingLogin = deferred<{ access_token: string; token_type: string; expires_in: number }>();
    vi.mocked(api.login).mockReturnValue(pendingLogin.promise);
    render(<App />);
    enterCredentials();
    const submit = screen.getByRole("button", { name: t("login:submit") });

    fireEvent.click(submit);
    expect(api.login).toHaveBeenCalledTimes(1);
    expect(api.login).toHaveBeenCalledWith(credentials.email, credentials.password);
    expect(localStorage.length).toBe(0);
    expect((submit as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(submit);
    expect(api.login).toHaveBeenCalledTimes(1);

    pendingLogin.resolve({ access_token: "synthetic-access-token", token_type: "bearer", expires_in: 3600 });
    expect(await screen.findByText("Meeting list")).toBeTruthy();
  });

  it("stores only the access token, clears transient password state and opens the portal on success", async () => {
    vi.mocked(api.login).mockResolvedValue({
      access_token: "synthetic-access-token",
      token_type: "bearer",
      expires_in: 3600,
    });
    render(<App />);
    enterCredentials();
    fireEvent.click(screen.getByRole("button", { name: t("login:submit") }));

    await screen.findByText("Meeting list");
    expect(localStorage.getItem("sauri_token")).toBe("synthetic-access-token");
    expect(localStorage.length).toBe(1);
    expect(localStorage.getItem("synthetic-password")).toBeNull();
    expect(screen.queryByLabelText(t("login:passwordLabel"))).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: t("shell:profile.fallbackName") }));
    fireEvent.click(screen.getByRole("menuitem", { name: t("shell:logout") }));
    expect(screen.getByLabelText(t("login:passwordLabel"))).toHaveProperty("value", "");
  });

  it.each([
    ["rejected credentials", () => Promise.reject(new Error("synthetic rejection"))],
    ["network failure", () => Promise.reject(new TypeError("synthetic network failure"))],
  ])("remains unauthenticated and shows a generic error after %s", async (_failure, response) => {
    vi.mocked(api.login).mockImplementation(response);
    render(<App />);
    enterCredentials();
    fireEvent.click(screen.getByRole("button", { name: t("login:submit") }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByLabelText(t("login:emailLabel"))).toBeTruthy();
    expect(screen.getByLabelText(t("login:passwordLabel"))).toHaveProperty("value", credentials.password);
    expect(localStorage.getItem("sauri_token")).toBeNull();
    expect(localStorage.getItem("synthetic-password")).toBeNull();
  });

  it("opens the portal when a token already exists", () => {
    localStorage.setItem("sauri_token", "synthetic-existing-token");

    openPortal();

    expect(screen.getByText("Meeting list")).toBeTruthy();
    expect(screen.getByRole("button", { name: t("shell:profile.fallbackName") })).toBeTruthy();
    expect(screen.queryByLabelText(t("login:passwordLabel"))).toBeNull();
  });

  it("logs out locally by removing only sauri_token without making a server request", async () => {
    localStorage.setItem("sauri_token", "synthetic-existing-token");
    localStorage.setItem("unrelated_preference", "keep-me");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    openPortal();

    fireEvent.click(screen.getByRole("button", { name: t("shell:profile.fallbackName") }));
    fireEvent.click(screen.getByRole("menuitem", { name: t("shell:logout") }));

    await waitFor(() => expect(screen.getByLabelText(t("login:emailLabel"))).toBeTruthy());
    expect(localStorage.getItem("sauri_token")).toBeNull();
    expect(localStorage.getItem("unrelated_preference")).toBe("keep-me");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(api.login).not.toHaveBeenCalled();
  });
});
