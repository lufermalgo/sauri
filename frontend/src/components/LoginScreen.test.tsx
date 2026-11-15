// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { LoginScreen } from "./LoginScreen";
import * as api from "../api";
import { copy } from "../copy/es";

const text = copy.login;

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual, login: vi.fn() };
});

const credentials = { email: "owner@example.test", password: "synthetic-password" };
const tokenResponse = { access_token: "synthetic-access-token", token_type: "bearer", expires_in: 3600 };

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

function enterCredentials() {
  fireEvent.change(screen.getByLabelText(text.emailLabel), { target: { value: credentials.email } });
  fireEvent.change(screen.getByLabelText(text.passwordLabel), { target: { value: credentials.password } });
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

describe("login screen", () => {
  it("shows the brand, title, and only the email and password fields", () => {
    const { container } = render(<LoginScreen onLogin={vi.fn()} />);

    expect(screen.getByText(text.brand)).toBeTruthy();
    expect(screen.getByRole("heading", { name: text.title })).toBeTruthy();
    expect(screen.getByRole("button", { name: text.submit })).toBeTruthy();
    const email = screen.getByLabelText(text.emailLabel) as HTMLInputElement;
    const password = screen.getByLabelText(text.passwordLabel) as HTMLInputElement;
    expect(email.type).toBe("email");
    expect(email.autocomplete).toBe("username");
    expect(email.required).toBe(true);
    expect(password.type).toBe("password");
    expect(password.autocomplete).toBe("current-password");
    expect(password.required).toBe(true);
    expect(container.querySelectorAll("input")).toHaveLength(2);
    expect(container.querySelectorAll("a")).toHaveLength(0);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("calls login once with exactly the typed credentials and disables the form while waiting", async () => {
    const pendingLogin = deferred<typeof tokenResponse>();
    vi.mocked(api.login).mockReturnValue(pendingLogin.promise);
    const onLogin = vi.fn();
    render(<LoginScreen onLogin={onLogin} />);
    enterCredentials();

    fireEvent.click(screen.getByRole("button", { name: text.submit }));
    const submit = await screen.findByRole("button", { name: text.submitting }) as HTMLButtonElement;

    expect(api.login).toHaveBeenCalledTimes(1);
    expect(api.login).toHaveBeenCalledWith(credentials.email, credentials.password);
    expect(submit.disabled).toBe(true);
    expect((screen.getByLabelText(text.emailLabel) as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText(text.passwordLabel) as HTMLInputElement).disabled).toBe(true);
    expect(localStorage.length).toBe(0);
    expect(onLogin).not.toHaveBeenCalled();

    fireEvent.click(submit);
    expect(api.login).toHaveBeenCalledTimes(1);

    pendingLogin.resolve(tokenResponse);
    await screen.findByRole("button", { name: text.submit });
  });

  it("stores only the access token, clears the password and calls onLogin on success", async () => {
    vi.mocked(api.login).mockResolvedValue(tokenResponse);
    const onLogin = vi.fn();
    render(<LoginScreen onLogin={onLogin} />);
    enterCredentials();

    fireEvent.click(screen.getByRole("button", { name: text.submit }));

    await vi.waitFor(() => expect(onLogin).toHaveBeenCalledTimes(1));
    expect(localStorage.getItem("sauri_token")).toBe("synthetic-access-token");
    expect(localStorage.length).toBe(1);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByLabelText(text.passwordLabel)).toHaveProperty("value", "");
  });

  it.each([
    ["rejected credentials", () => Promise.reject(new Error("synthetic rejection"))],
    ["network failure", () => Promise.reject(new TypeError("synthetic network failure"))],
  ])("stores no token and shows the error after %s", async (_failure, response) => {
    vi.mocked(api.login).mockImplementation(response);
    const onLogin = vi.fn();
    render(<LoginScreen onLogin={onLogin} />);
    enterCredentials();

    fireEvent.click(screen.getByRole("button", { name: text.submit }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(text.error);
    expect(onLogin).not.toHaveBeenCalled();
    expect(localStorage.getItem("sauri_token")).toBeNull();
    expect(localStorage.length).toBe(0);
    expect(screen.getByLabelText(text.emailLabel)).toHaveProperty("value", credentials.email);
    expect(screen.getByLabelText(text.passwordLabel)).toHaveProperty("value", credentials.password);
    expect((screen.getByRole("button", { name: text.submit }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("clears a previous error when submitting again", async () => {
    vi.mocked(api.login).mockRejectedValueOnce(new Error("synthetic rejection"));
    vi.mocked(api.login).mockResolvedValueOnce(tokenResponse);
    render(<LoginScreen onLogin={vi.fn()} />);
    enterCredentials();

    fireEvent.click(screen.getByRole("button", { name: text.submit }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: text.submit }));

    await vi.waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(api.login).toHaveBeenCalledTimes(2);
  });
});
