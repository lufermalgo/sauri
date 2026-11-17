// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { LoginScreen } from "./LoginScreen";
import * as api from "../api";
import { t } from "../i18n";

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

describe("login screen", () => {
  it("shows the lockup heading, subtitle and only the email and password fields as inputs", () => {
    const { container } = render(<LoginScreen onLogin={vi.fn()} />);

    // The logo is the product name: the heading still reads "<lead> Sauri" for assistive technology.
    const heading = screen.getByRole("heading", { level: 1, name: `${t("login:titleLead")} ${t("shell:brand")}` });
    expect(heading.querySelector('svg[role="img"]')!.getAttribute("aria-label")).toBe(t("shell:brand"));
    expect(heading.querySelector(".ui-brand-word")).toBeTruthy();
    expect(heading.textContent).toBe(`${t("login:titleLead")} `);
    // The isotype now lives in the lockup: there is no separate tile above the heading.
    expect(container.querySelector(".login-brand")).toBeNull();
    expect(container.querySelectorAll("svg polygon[fill='#9A8CE0']")).toHaveLength(1);
    expect(screen.getByText(t("login:subtitle"))).toBeTruthy();
    expect(screen.getByRole("button", { name: t("login:submit") })).toBeTruthy();
    const email = screen.getByLabelText(t("login:emailLabel")) as HTMLInputElement;
    const password = screen.getByLabelText(t("login:passwordLabel")) as HTMLInputElement;
    expect(email.type).toBe("email");
    expect(email.autocomplete).toBe("username");
    expect(email.required).toBe(true);
    expect(password.type).toBe("password");
    expect(password.autocomplete).toBe("current-password");
    expect(password.required).toBe(true);
    // The language choice adds radios; the sign-in form itself still has only these two fields.
    expect(container.querySelectorAll("input:not([type=radio])")).toHaveLength(2);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows the reference's future options visibly but inert: aria-disabled, focusable, 'Coming soon' description", () => {
    const { container } = render(<LoginScreen onLogin={vi.fn()} />);
    const soonText = t("login:soon");

    const links = [
      t("login:forgotPassword"),
      t("login:joinFree"),
      t("login:legalTerms"),
      t("login:legalPrivacy"),
      t("login:legalDataNotice"),
    ].map((name) => screen.getByRole("link", { name }));
    const google = screen.getByRole("button", { name: t("login:continueWithGoogle") });
    expect(links).toHaveLength(5);
    for (const control of [...links, google]) {
      expect(control.getAttribute("aria-disabled")).toBe("true");
      expect(control.getAttribute("href")).toBeNull();
      expect(control.tabIndex).toBe(0);
      const description = document.getElementById(control.getAttribute("aria-describedby")!)!;
      expect(description.textContent).toBe(soonText);
      expect(description.getAttribute("role")).toBe("tooltip");
    }
    expect((google as HTMLButtonElement).disabled).toBe(false); // aria-disabled only: it must stay focusable
    expect(google.querySelector("svg")!.getAttribute("aria-hidden")).toBe("true");
    expect(google.querySelectorAll("svg path")).toHaveLength(4);
    expect(screen.getByText(t("login:providersSeparator"))).toBeTruthy();
    expect(screen.getByText(t("login:newToSauri"), { exact: false })).toBeTruthy();
    // Exactly the five links and the Google button: nothing else became a link.
    expect(container.querySelectorAll("a")).toHaveLength(5);
  });

  it("does nothing when an inert option is activated", () => {
    const onLogin = vi.fn();
    render(<LoginScreen onLogin={onLogin} />);
    enterCredentials();

    fireEvent.click(screen.getByRole("button", { name: t("login:continueWithGoogle") }));
    for (const name of [t("login:forgotPassword"), t("login:joinFree"), t("login:legalTerms")]) {
      const link = screen.getByRole("link", { name });
      fireEvent.click(link);
      fireEvent.keyDown(link, { key: "Enter" });
    }

    expect(api.login).not.toHaveBeenCalled();
    expect(onLogin).not.toHaveBeenCalled();
  });

  it("keeps the submit button disabled until both fields are filled", () => {
    render(<LoginScreen onLogin={vi.fn()} />);
    const submit = screen.getByRole("button", { name: t("login:submit") }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText(t("login:emailLabel")), { target: { value: credentials.email } });
    expect(submit.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText(t("login:passwordLabel")), { target: { value: credentials.password } });
    expect(submit.disabled).toBe(false);

    fireEvent.change(screen.getByLabelText(t("login:emailLabel")), { target: { value: "   " } });
    expect(submit.disabled).toBe(true);
  });

  it("does not call login when submitted with an empty field", () => {
    render(<LoginScreen onLogin={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(t("login:emailLabel")), { target: { value: credentials.email } });

    fireEvent.submit(screen.getByLabelText(t("login:emailLabel")).closest("form")!);

    expect(api.login).not.toHaveBeenCalled();
  });

  it("submits through the form's own submit path, which is what Enter triggers", async () => {
    vi.mocked(api.login).mockResolvedValue(tokenResponse);
    const onLogin = vi.fn();
    render(<LoginScreen onLogin={onLogin} />);
    enterCredentials();

    // Implicit submission by Enter is browser behavior (checked in the browser pass); here the form submits itself.
    (screen.getByLabelText(t("login:passwordLabel")).closest("form") as HTMLFormElement).requestSubmit();

    await vi.waitFor(() => expect(onLogin).toHaveBeenCalledTimes(1));
    expect(api.login).toHaveBeenCalledWith(credentials.email, credentials.password);
  });

  it("toggles the password between hidden and visible with an accessible name", () => {
    render(<LoginScreen onLogin={vi.fn()} />);
    const password = screen.getByLabelText(t("login:passwordLabel")) as HTMLInputElement;
    expect(password.type).toBe("password");

    fireEvent.click(screen.getByRole("button", { name: t("login:showPassword") }));
    expect(password.type).toBe("text");
    expect(screen.queryByRole("button", { name: t("login:showPassword") })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: t("login:hidePassword") }));
    expect(password.type).toBe("password");
    expect(screen.getByRole("button", { name: t("login:showPassword") })).toBeTruthy();
  });

  it("renders the given providers instead of the default ones, and an active one works", () => {
    const onSelect = vi.fn();
    render(<LoginScreen onLogin={vi.fn()} providers={[{ id: "test", label: "Continuar con prueba", onSelect }]} />);

    expect(screen.queryByRole("button", { name: t("login:continueWithGoogle") })).toBeNull();
    const button = screen.getByRole("button", { name: "Continuar con prueba" });
    expect(button.getAttribute("aria-disabled")).toBeNull();
    fireEvent.click(button);
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("calls login once with exactly the typed credentials and disables the form while waiting", async () => {
    const pendingLogin = deferred<typeof tokenResponse>();
    vi.mocked(api.login).mockReturnValue(pendingLogin.promise);
    const onLogin = vi.fn();
    render(<LoginScreen onLogin={onLogin} />);
    enterCredentials();

    fireEvent.click(screen.getByRole("button", { name: t("login:submit") }));
    const submit = await screen.findByRole("button", { name: t("login:submitting") }) as HTMLButtonElement;

    expect(api.login).toHaveBeenCalledTimes(1);
    expect(api.login).toHaveBeenCalledWith(credentials.email, credentials.password);
    expect(submit.disabled).toBe(true);
    expect((screen.getByLabelText(t("login:emailLabel")) as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText(t("login:passwordLabel")) as HTMLInputElement).disabled).toBe(true);
    expect(localStorage.length).toBe(0);
    expect(onLogin).not.toHaveBeenCalled();

    fireEvent.click(submit);
    expect(api.login).toHaveBeenCalledTimes(1);

    pendingLogin.resolve(tokenResponse);
    await screen.findByRole("button", { name: t("login:submit") });
  });

  it("stores only the access token, clears the password and calls onLogin on success", async () => {
    vi.mocked(api.login).mockResolvedValue(tokenResponse);
    const onLogin = vi.fn();
    render(<LoginScreen onLogin={onLogin} />);
    enterCredentials();

    fireEvent.click(screen.getByRole("button", { name: t("login:submit") }));

    await vi.waitFor(() => expect(onLogin).toHaveBeenCalledTimes(1));
    expect(localStorage.getItem("sauri_token")).toBe("synthetic-access-token");
    expect(localStorage.length).toBe(1);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByLabelText(t("login:passwordLabel"))).toHaveProperty("value", "");
  });

  it.each([
    ["rejected credentials", () => Promise.reject(new Error("synthetic rejection"))],
    ["network failure", () => Promise.reject(new TypeError("synthetic network failure"))],
  ])("stores no token and shows the error after %s", async (_failure, response) => {
    vi.mocked(api.login).mockImplementation(response);
    const onLogin = vi.fn();
    render(<LoginScreen onLogin={onLogin} />);
    enterCredentials();

    fireEvent.click(screen.getByRole("button", { name: t("login:submit") }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(t("login:error"));
    expect(onLogin).not.toHaveBeenCalled();
    expect(localStorage.getItem("sauri_token")).toBeNull();
    expect(localStorage.length).toBe(0);
    expect(screen.getByLabelText(t("login:emailLabel"))).toHaveProperty("value", credentials.email);
    expect(screen.getByLabelText(t("login:passwordLabel"))).toHaveProperty("value", credentials.password);
    expect((screen.getByRole("button", { name: t("login:submit") }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("clears a previous error when submitting again", async () => {
    vi.mocked(api.login).mockRejectedValueOnce(new Error("synthetic rejection"));
    vi.mocked(api.login).mockResolvedValueOnce(tokenResponse);
    render(<LoginScreen onLogin={vi.fn()} />);
    enterCredentials();

    fireEvent.click(screen.getByRole("button", { name: t("login:submit") }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: t("login:submit") }));

    await vi.waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(api.login).toHaveBeenCalledTimes(2);
  });
});
