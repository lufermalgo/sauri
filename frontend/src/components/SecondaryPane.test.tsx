// @vitest-environment jsdom
/**
 * Secondary panes: the sidebar item of a section with a second pane (library list, settings
 * categories) shows or hides it. One hook and one contract serve both; everywhere else the item is
 * a plain link without toggle semantics.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { PortalShell } from "./PortalShell";
import { SettingsView } from "./SettingsView";
import {
  LIBRARY_PANE_STORAGE_KEY,
  SETTINGS_PANE_ID,
  SETTINGS_PANE_STORAGE_KEY,
  hiddenPaneAttributes,
  useSecondaryPane,
} from "./useSecondaryPane";
import { SETTINGS_CATEGORIES, type Route } from "../router";
import { t } from "../i18n";

const owner = { name: "Ana Maria Perez", email: "ana@example.test" };

let viewportWidth = 1440;
const listeners = new Set<() => void>();

function stubViewport(width: number) {
  viewportWidth = width;
  vi.stubGlobal("matchMedia", (query: string) => ({
    get matches() {
      const min = /min-width:\s*(\d+)/.exec(query);
      const max = /max-width:\s*(\d+)/.exec(query);
      return (min ? viewportWidth >= Number(min[1]) : true) && (max ? viewportWidth <= Number(max[1]) : true);
    },
    media: query,
    addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
  }));
}

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

function blockedStorage(): Storage {
  const fail = () => { throw new DOMException("blocked", "SecurityError"); };
  return { get length() { return 0; }, clear: fail, getItem: fail, key: fail, removeItem: fail, setItem: fail };
}

function shellFor(route: Route) {
  return (
    <PortalShell route={route} user={owner} onLogout={vi.fn()}>
      {route.name === "settings" ? <SettingsView route={route} user={owner} onLogout={vi.fn()} /> : "content"}
    </PortalShell>
  );
}

function renderShell(route: Route) {
  return render(shellFor(route));
}

const settingsRoute = (category: (typeof SETTINGS_CATEGORIES)[number] = "appearance"): Route => ({ name: "settings", category });
const gear = () => screen.getByRole("button", { name: t("shell:profile.settings") });
const slot = () => document.getElementById(SETTINGS_PANE_ID)!;
const tipOf = (control: HTMLElement) => document.getElementById(control.getAttribute("aria-describedby") ?? "") as HTMLElement;

beforeEach(() => {
  listeners.clear();
  stubViewport(1440);
  vi.stubGlobal("localStorage", createLocalStorage());
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

describe("useSecondaryPane", () => {
  it("starts shown and stores the choice under its own key", () => {
    const { result } = renderHook(() => useSecondaryPane("sauri_test_pane_hidden"));
    expect(result.current.hidden).toBe(false);
    act(() => result.current.toggle());
    expect(result.current.hidden).toBe(true);
    expect(localStorage.getItem("sauri_test_pane_hidden")).toBe("1");
    act(() => result.current.toggle());
    expect(result.current.hidden).toBe(false);
    expect(localStorage.getItem("sauri_test_pane_hidden")).toBe("0");
  });

  it("restores a stored choice and shares it between instances of the same pane only", () => {
    localStorage.setItem(SETTINGS_PANE_STORAGE_KEY, "1");
    const first = renderHook(() => useSecondaryPane(SETTINGS_PANE_STORAGE_KEY));
    const second = renderHook(() => useSecondaryPane(SETTINGS_PANE_STORAGE_KEY));
    const library = renderHook(() => useSecondaryPane(LIBRARY_PANE_STORAGE_KEY));
    expect(first.result.current.hidden).toBe(true);
    expect(library.result.current.hidden).toBe(false);
    act(() => second.result.current.setHidden(false));
    expect(first.result.current.hidden).toBe(false);
    expect(library.result.current.hidden).toBe(false);
    act(() => library.result.current.toggle());
    expect(library.result.current.hidden).toBe(true);
    expect(first.result.current.hidden).toBe(false);
  });

  it("keeps the choice for the visit when storage is blocked", () => {
    vi.stubGlobal("localStorage", blockedStorage());
    const { result } = renderHook(() => useSecondaryPane("sauri_blocked_pane_hidden"));
    expect(result.current.hidden).toBe(false);
    act(() => result.current.toggle());
    expect(result.current.hidden).toBe(true);
    act(() => result.current.toggle());
    expect(result.current.hidden).toBe(false);
  });

  it("describes a hidden slot as collapsed, inert and out of the accessibility tree", () => {
    expect(hiddenPaneAttributes(true)).toEqual({ "data-hidden": true, "aria-hidden": true, inert: "" });
    expect(hiddenPaneAttributes(false)).toEqual({ "data-hidden": undefined, "aria-hidden": undefined });
  });
});

describe("settings categories pane toggle in the side panel", () => {
  it("makes the gear a button that carries the pane's state and keeps the settings name", () => {
    renderShell(settingsRoute());
    expect(screen.queryByRole("link", { name: t("shell:profile.settings") })).toBeNull();
    expect(gear()).toHaveAttribute("aria-expanded", "true");
    expect(gear().getAttribute("aria-controls")).toBe(SETTINGS_PANE_ID);
    expect(gear()).toHaveAttribute("aria-current", "page");
    expect(slot()).not.toHaveAttribute("data-hidden");
    expect(slot().querySelector("nav")).not.toBeNull();
  });

  it("hides and shows the categories, keeping focus on the gear and remembering the choice", () => {
    renderShell(settingsRoute());
    act(() => gear().focus());

    fireEvent.click(gear());
    expect(slot()).toHaveAttribute("data-hidden");
    expect(slot()).toHaveAttribute("aria-hidden", "true");
    expect(slot()).toHaveAttribute("inert");
    expect(screen.queryByRole("navigation", { name: t("settings:navLabel") })).toBeNull();
    expect(gear()).toHaveAttribute("aria-expanded", "false");
    expect(gear()).toHaveFocus();
    expect(localStorage.getItem(SETTINGS_PANE_STORAGE_KEY)).toBe("1");
    // The category stays open and the library pane is untouched.
    expect(screen.getByRole("heading", { level: 2, name: t("settings:categories.appearance.label") })).toBeInTheDocument();
    expect(localStorage.getItem(LIBRARY_PANE_STORAGE_KEY)).toBeNull();

    fireEvent.click(gear());
    expect(slot()).not.toHaveAttribute("data-hidden");
    expect(slot()).not.toHaveAttribute("inert");
    expect(screen.getByRole("navigation", { name: t("settings:navLabel") })).toBeInTheDocument();
    expect(gear()).toHaveAttribute("aria-expanded", "true");
    expect(gear()).toHaveFocus();
    expect(localStorage.getItem(SETTINGS_PANE_STORAGE_KEY)).toBe("0");
  });

  it("is a native button, so Enter and Space activate it", () => {
    renderShell(settingsRoute());
    expect(gear().tagName).toBe("BUTTON");
    expect(gear()).toHaveAttribute("type", "button");
  });

  it("describes the action with a tooltip: hide when shown, show when hidden", () => {
    renderShell(settingsRoute());
    vi.useFakeTimers();
    expect(tipOf(gear())).toHaveTextContent(t("shell:settingsPane.hide"));
    expect(tipOf(gear())).toHaveAttribute("role", "tooltip");
    fireEvent.mouseEnter(gear());
    act(() => { vi.advanceTimersByTime(400); });
    expect(tipOf(gear()).hidden).toBe(false);
    fireEvent.click(gear());
    expect(tipOf(gear())).toHaveTextContent(t("shell:settingsPane.show"));
  });

  it("keeps the pane mounted while hidden, so the search text is still there", () => {
    renderShell(settingsRoute());
    const search = screen.getByRole("searchbox", { name: t("settings:search.label") });
    fireEvent.change(search, { target: { value: "tema" } });
    fireEvent.click(gear());
    expect(search.isConnected).toBe(true);
    expect(slot().contains(search)).toBe(true);
    fireEvent.click(gear());
    expect(screen.getByRole("searchbox", { name: t("settings:search.label") })).toHaveValue("tema");
  });

  it("remembers a hidden pane on the next visit and keeps it hidden when a deep link changes the category", () => {
    localStorage.setItem(SETTINGS_PANE_STORAGE_KEY, "1");
    const { rerender } = renderShell(settingsRoute("appearance"));
    expect(slot()).toHaveAttribute("data-hidden");
    expect(gear()).toHaveAttribute("aria-expanded", "false");
    rerender(shellFor(settingsRoute("summaries")));
    expect(screen.getByRole("heading", { level: 2, name: t("settings:categories.summaries.label") })).toBeInTheDocument();
    expect(slot()).toHaveAttribute("data-hidden");
    expect(gear()).toHaveAttribute("aria-expanded", "false");
  });

  it("works for the visit when storage is blocked", () => {
    vi.stubGlobal("localStorage", blockedStorage());
    renderShell(settingsRoute());
    fireEvent.click(gear());
    expect(slot()).toHaveAttribute("data-hidden");
    fireEvent.click(gear());
    expect(slot()).not.toHaveAttribute("data-hidden");
  });

  it("shows the library item as a plain link while on settings", () => {
    renderShell(settingsRoute());
    const link = screen.getByRole("link", { name: t("shell:library") });
    expect(link).not.toHaveAttribute("aria-expanded");
    expect(link).not.toHaveAttribute("aria-controls");
  });

  it("keeps the two steps under 640px: the gear is a link and a stored hidden pane never hides the list", () => {
    stubViewport(600);
    localStorage.setItem(SETTINGS_PANE_STORAGE_KEY, "1");
    renderShell({ name: "settings" });
    expect(screen.getByRole("link", { name: new RegExp(`^${t("settings:categories.account.label")}`) })).toBeInTheDocument();
    expect(slot()).not.toHaveAttribute("data-hidden");
    expect(slot()).not.toHaveAttribute("inert");
    // The drawer holds the gear while it is closed; its item is a link with no toggle semantics.
    const link = screen.getByRole("link", { name: t("shell:profile.settings"), hidden: true });
    expect(link).not.toHaveAttribute("aria-expanded");
    expect(screen.queryByRole("button", { name: t("shell:profile.settings"), hidden: true })).toBeNull();
  });

  it("shows the sidebar as a rail with the tooltip beside the gear", () => {
    localStorage.setItem("sauri_sidebar_collapsed", "1");
    renderShell(settingsRoute());
    expect(document.querySelector(".shell-root")).toHaveAttribute("data-mode", "rail");
    expect(gear()).toHaveAccessibleName(t("shell:profile.settings"));
    expect(tipOf(gear())).toHaveTextContent(t("shell:settingsPane.hide"));
  });
});

describe("items without a secondary pane", () => {
  it("makes Biblioteca the list pane's toggle on the library route too, with its state in the tooltip", () => {
    localStorage.setItem(LIBRARY_PANE_STORAGE_KEY, "1");
    renderShell({ name: "library" });
    const button = screen.getByRole("button", { name: t("shell:library") });
    expect(button).toHaveAttribute("aria-current", "page");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveAttribute("aria-controls", "library-pane");
    expect(screen.queryByRole("link", { name: t("shell:library") })).toBeNull();
    expect(tipOf(button)).toHaveTextContent(t("shell:libraryPane.show"));
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(tipOf(button)).toHaveTextContent(t("shell:libraryPane.hide"));
    expect(localStorage.getItem(LIBRARY_PANE_STORAGE_KEY)).toBe("0");
  });

  it("keeps Biblioteca a plain link below 1100px, named by a tooltip that only says its name", () => {
    stubViewport(900);
    localStorage.setItem("sauri_sidebar_collapsed", "0"); // below 1320px the sidebar starts as a rail
    localStorage.setItem(LIBRARY_PANE_STORAGE_KEY, "1");
    renderShell({ name: "library" });
    const link = screen.getByRole("link", { name: t("shell:library") });
    expect(link).toHaveAttribute("aria-current", "page");
    expect(link).not.toHaveAttribute("aria-expanded");
    expect(link).not.toHaveAttribute("aria-controls");
    expect(screen.queryByRole("button", { name: t("shell:library") })).toBeNull();
    expect(tipOf(link)).toHaveTextContent(new RegExp(`^${t("shell:library")}$`));
    expect(tipOf(link).textContent).not.toMatch(/ocultar|mostrar/i);
  });

  it("keeps the gear a plain link outside settings, whatever the stored settings choice", () => {
    localStorage.setItem(SETTINGS_PANE_STORAGE_KEY, "1");
    renderShell({ name: "library" });
    const link = screen.getByRole("link", { name: t("shell:profile.settings") });
    expect(link).toHaveAttribute("href", "/settings");
    expect(link).not.toHaveAttribute("aria-expanded");
    expect(screen.queryByRole("button", { name: t("shell:profile.settings") })).toBeNull();
  });

  it("keeps the gear a link with a recording open", () => {
    renderShell({ name: "meeting", meetingId: "b" });
    expect(screen.getByRole("button", { name: t("shell:library") })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: t("shell:profile.settings") })).not.toHaveAttribute("aria-expanded");
  });
});

describe("settings pane styles", () => {
  const css = readFileSync(join(__dirname, "../styles/settings.css"), "utf8");

  it("collapses the slot with the shared transition and leaves the nav at its own width", () => {
    const slotRule = /\.settings-nav-slot\s*\{([^}]*)\}/.exec(css)?.[1] ?? "";
    expect(slotRule).toMatch(/overflow:\s*hidden/);
    expect(slotRule).toMatch(/transition:[^;]*flex-basis var\(--ds-duration\)/);
    const hiddenRule = /\.settings-nav-slot\[data-hidden\]\s*\{([^}]*)\}/.exec(css)?.[1] ?? "";
    expect(hiddenRule).toMatch(/width:\s*0/);
    expect(hiddenRule).toMatch(/visibility:\s*hidden/);
    expect(/\.settings-nav\s*\{[^}]*flex:\s*0 0 208px/.test(css)).toBe(true);
  });
});
