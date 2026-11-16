// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { PortalShell } from "./PortalShell";
import { copy } from "../copy/es";

const owner = { name: "Ana Maria Perez", email: "ana@example.test" };
const STORAGE_KEY = "sauri_sidebar_collapsed";

type Listener = () => void;
let viewportWidth = 1440;
const listeners = new Set<Listener>();

function maxWidthOf(query: string): number {
  return Number(/max-width:\s*(\d+)px/.exec(query)?.[1] ?? Number.POSITIVE_INFINITY);
}

function stubViewport(width: number) {
  viewportWidth = width;
  vi.stubGlobal("matchMedia", (query: string) => ({
    get matches() { return viewportWidth <= maxWidthOf(query); },
    media: query,
    addEventListener: (_type: string, listener: Listener) => listeners.add(listener),
    removeEventListener: (_type: string, listener: Listener) => listeners.delete(listener),
  }));
}

function resizeTo(width: number) {
  act(() => {
    viewportWidth = width;
    listeners.forEach((listener) => listener());
  });
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

function renderShell(props: Partial<Parameters<typeof PortalShell>[0]> = {}) {
  return render(
    <PortalShell route={{ name: "library" }} user={owner} onLogout={vi.fn()} {...props}>content</PortalShell>,
  );
}

const root = () => document.querySelector<HTMLElement>(".shell-root")!;
const sidebar = () => screen.getByRole("complementary", { name: copy.shell.sidebar.region });

beforeEach(() => {
  listeners.clear();
  stubViewport(1440);
  vi.stubGlobal("localStorage", createLocalStorage());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});

describe("PortalShell navigation and profile", () => {
  it("renders the library link, the profile card and no top bar or upload link", () => {
    renderShell({ route: { name: "upload" } });
    expect(screen.getByRole("navigation", { name: copy.shell.navLabel })).toBeTruthy();
    expect(screen.getByRole("link", { name: copy.shell.library })).toHaveProperty("pathname", "/");
    expect(screen.queryByRole("link", { name: copy.shell.upload })).toBeNull();
    expect(screen.queryByRole("banner")).toBeNull();
    expect(screen.getByText(owner.name)).toBeTruthy();
    expect(screen.getByText(owner.email)).toBeTruthy();
    expect(screen.getByRole("button", { name: copy.shell.profile.menu(`${owner.name}, ${owner.email}`) })).toBeTruthy();
    expect(screen.getByRole("link", { name: copy.shell.profile.settings })).toHaveProperty("pathname", "/settings");
  });

  it("shows initials from the name, the email local part, or a generic icon", () => {
    const { unmount } = renderShell();
    expect(document.querySelector(".ui-avatar")?.textContent).toBe("AP");
    unmount();
    renderShell({ user: { name: null, email: "luis.fer@example.test" } });
    expect(document.querySelector(".ui-avatar")?.textContent).toBe("LF");
    cleanup();
    renderShell({ user: null });
    expect(document.querySelector(".ui-avatar")?.textContent).toBe("");
    expect(document.querySelector(".ui-avatar svg")).toBeTruthy();
  });

  it("leads with the email when the token has no name and never invents one", () => {
    renderShell({ user: { name: null, email: owner.email } });
    expect(document.querySelector(".shell-profile-name")?.textContent).toBe(owner.email);
    expect(document.querySelector(".shell-profile-email")).toBeNull();
    expect(screen.getByRole("button", { name: copy.shell.profile.menu(owner.email) })).toBeTruthy();
  });

  it("falls back to a generic account label without user data", () => {
    renderShell({ user: null });
    expect(document.querySelector(".shell-profile-name")?.textContent).toBe(copy.shell.profile.fallbackName);
    expect(screen.getByRole("button", { name: copy.shell.profile.fallbackName })).toBeTruthy();
  });

  it("returns to the library without reloading and leaves modified clicks to the browser", () => {
    const listener = vi.fn();
    window.addEventListener("sauri:navigate", listener);
    window.history.replaceState({}, "", "/upload");
    renderShell({ route: { name: "upload" } });
    const link = screen.getByRole("link", { name: copy.shell.library });
    expect(link.getAttribute("aria-current")).toBeNull();

    let componentPrevented: boolean | null = null;
    const onWindowClick = (event: Event) => {
      componentPrevented = event.defaultPrevented;
      event.preventDefault();
    };
    window.addEventListener("click", onWindowClick);
    fireEvent.click(link, { ctrlKey: true });
    window.removeEventListener("click", onWindowClick);
    expect(componentPrevented).toBe(false);
    expect(window.location.pathname).toBe("/upload");

    fireEvent.click(link);
    expect(window.location.pathname).toBe("/");
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener("sauri:navigate", listener);
  });

  it("marks the library as the current page only on the library route", () => {
    const { unmount } = renderShell();
    // On the library route (wide) the item is the list pane's toggle and stays the current item.
    expect(screen.getByRole("button", { name: copy.shell.library }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: copy.shell.profile.settings }).getAttribute("aria-current")).toBeNull();
    unmount();
    renderShell({ route: { name: "settings" } });
    expect(screen.getByRole("link", { name: copy.shell.library }).getAttribute("aria-current")).toBeNull();
    // On settings the gear becomes the toggle of the categories pane and stays the current item.
    expect(screen.getByRole("button", { name: copy.shell.profile.settings }).getAttribute("aria-current")).toBe("page");
  });

  it("opens settings from the gear without reloading", () => {
    const listener = vi.fn();
    window.addEventListener("sauri:navigate", listener);
    renderShell();
    fireEvent.click(screen.getByRole("link", { name: copy.shell.profile.settings }));
    expect(window.location.pathname).toBe("/settings");
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener("sauri:navigate", listener);
  });

  it("signs out from the profile menu and offers nothing else there", () => {
    const onLogout = vi.fn();
    renderShell({ onLogout });
    expect(screen.queryByRole("menuitem")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: copy.shell.profile.menu(`${owner.name}, ${owner.email}`) }));
    expect(screen.getAllByRole("menuitem")).toHaveLength(1);
    fireEvent.click(screen.getByRole("menuitem", { name: copy.shell.logout }));
    expect(onLogout).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("renders children alone inside main", () => {
    renderShell();
    expect(screen.getByRole("main").textContent).toBe("content");
  });
});

describe("PortalShell collapse", () => {
  it("starts expanded on wide screens and toggles to the rail with aria-expanded", () => {
    renderShell();
    const toggle = screen.getByRole("button", { name: copy.shell.sidebar.toggle });
    expect(root().dataset.mode).toBe("full");
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(toggle.getAttribute("aria-controls")).toBe(sidebar().id);

    fireEvent.click(toggle);
    expect(root().dataset.mode).toBe("rail");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    // Labels stay in the document (visually hidden in the rail) so every control keeps its name.
    expect(screen.getByRole("button", { name: copy.shell.library })).toBeTruthy();
    expect(screen.getByRole("link", { name: copy.shell.profile.settings })).toBeTruthy();
    fireEvent.click(toggle);
    expect(root().dataset.mode).toBe("full");
  });

  it("remembers the choice per device", () => {
    const first = renderShell();
    fireEvent.click(screen.getByRole("button", { name: copy.shell.sidebar.toggle }));
    expect(localStorage.getItem(STORAGE_KEY)).toBe("1");
    first.unmount();

    renderShell();
    expect(root().dataset.mode).toBe("rail");
    fireEvent.click(screen.getByRole("button", { name: copy.shell.sidebar.toggle }));
    expect(localStorage.getItem(STORAGE_KEY)).toBe("0");
  });

  it("starts collapsed below 1320px unless the visitor chose otherwise", () => {
    stubViewport(1100);
    const first = renderShell();
    expect(root().dataset.mode).toBe("rail");
    first.unmount();

    localStorage.setItem(STORAGE_KEY, "0");
    renderShell();
    expect(root().dataset.mode).toBe("full");
  });

  it("works when storage is blocked", () => {
    const blocked = () => { throw new Error("blocked"); };
    vi.stubGlobal("localStorage", { ...createLocalStorage(), getItem: blocked, setItem: blocked });
    renderShell();
    expect(root().dataset.mode).toBe("full");
    fireEvent.click(screen.getByRole("button", { name: copy.shell.sidebar.toggle }));
    expect(root().dataset.mode).toBe("rail");
  });
});

describe("PortalShell drawer", () => {
  beforeEach(() => stubViewport(375));

  const opener = () => screen.getByRole("button", { name: copy.shell.sidebar.open });
  const closer = () => screen.getByRole("button", { name: copy.shell.sidebar.close });

  it("shows a slim top bar with a closed drawer and no collapse toggle", () => {
    renderShell();
    expect(root().dataset.mode).toBe("drawer");
    expect(screen.getByRole("banner")).toBeTruthy();
    expect(opener().getAttribute("aria-expanded")).toBe("false");
    expect(sidebar().dataset.open).toBe("false");
    expect(screen.queryByRole("button", { name: copy.shell.sidebar.toggle })).toBeNull();
    expect(document.querySelector(".shell-backdrop")).toBeNull();
  });

  it("moves focus in on open and back to the opener on Escape", () => {
    renderShell();
    opener().focus();
    fireEvent.click(opener());
    expect(opener().getAttribute("aria-expanded")).toBe("true");
    expect(sidebar().dataset.open).toBe("true");
    expect(closer()).toHaveProperty("ownerDocument.activeElement", closer());

    fireEvent.keyDown(document, { key: "Escape" });
    expect(sidebar().dataset.open).toBe("false");
    expect(document.activeElement).toBe(opener());
  });

  it("closes from the backdrop and from the close button", () => {
    renderShell();
    fireEvent.click(opener());
    fireEvent.click(document.querySelector(".shell-backdrop")!);
    expect(sidebar().dataset.open).toBe("false");
    expect(document.activeElement).toBe(opener());

    fireEvent.click(opener());
    fireEvent.click(closer());
    expect(sidebar().dataset.open).toBe("false");
  });

  it("closes after navigating from the drawer", () => {
    renderShell();
    fireEvent.click(opener());
    fireEvent.click(screen.getByRole("link", { name: copy.shell.profile.settings }));
    expect(window.location.pathname).toBe("/settings");
    expect(sidebar().dataset.open).toBe("false");
  });

  it("keeps Tab inside the open drawer", () => {
    renderShell();
    fireEvent.click(opener());
    const items = Array.from(sidebar().querySelectorAll<HTMLElement>("a[href], button"));
    const first = items[0];
    const last = items[items.length - 1];
    last.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
  });

  it("leaves Escape to an open account menu first", () => {
    renderShell();
    fireEvent.click(opener());
    fireEvent.click(screen.getByRole("button", { name: copy.shell.profile.menu(`${owner.name}, ${owner.email}`) }));
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(sidebar().dataset.open).toBe("true");
  });

  it("drops the drawer when the viewport grows", () => {
    renderShell();
    fireEvent.click(opener());
    resizeTo(1440);
    expect(root().dataset.mode).toBe("full");
    expect(screen.queryByRole("banner")).toBeNull();
    resizeTo(375);
    expect(sidebar().dataset.open).toBe("false");
  });
});

describe("PortalShell app frame", () => {
  const shellCss = readFileSync(join(__dirname, "../styles/shell.css"), "utf8");
  const tokensCss = readFileSync(join(__dirname, "../design/tokens.css"), "utf8");
  const rule = (selector: string) =>
    new RegExp(`(?:^|\\n)${selector.replace(/[.[\]"=-]/g, "\\$&")}\\s*\\{([^}]*)\\}`).exec(shellCss)?.[1] ?? "";

  it("renders the page inside the one content region, next to the side panel", () => {
    renderShell();
    const regions = document.querySelectorAll(".shell-content");
    expect(regions).toHaveLength(1);
    expect(regions[0].parentElement).toBe(root());
    expect(regions[0].contains(screen.getByRole("main"))).toBe(true);
    expect(sidebar().parentElement).toBe(root());
  });

  it("pins the frame to the window; the content region never scrolls, each view owns its panes", () => {
    expect(rule(".shell-root")).toMatch(/position:\s*fixed/);
    expect(rule(".shell-root")).toMatch(/inset:\s*0/);
    expect(rule(".shell-root")).not.toMatch(/(?<!-)height:/);
    expect(rule(".shell-content")).toMatch(/overflow:\s*hidden/);
    expect(rule(".shell-content")).toMatch(/min-height:\s*0/);
    expect(rule(".shell-content")).toMatch(/position:\s*relative/);
    expect(rule(".shell-sidebar")).not.toMatch(/overflow/);
    // A single-column view scrolls inside its own body, under its pane header strip.
    expect(rule(".app-view-body")).toMatch(/overflow-y:\s*auto/);
    expect(rule(".app-view-body")).toMatch(/min-height:\s*0/);
  });

  it("sizes the side panel for a desktop application: 220px, 60px rail, 32px rows, 13px labels", () => {
    expect(rule(".shell-root")).toMatch(/--shell-sidebar-width:\s*var\(--ds-sidebar-w\)/);
    expect(rule(".shell-link")).toMatch(/min-height:\s*var\(--ds-nav-row-h\)/);
    expect(rule(".shell-link")).toMatch(/font-size:\s*var\(--ds-text-sm\)/);
    expect(tokensCss).toMatch(/--ds-sidebar-w:\s*220px/);
    expect(tokensCss).toMatch(/--ds-rail-w:\s*60px/);
    expect(tokensCss).toMatch(/--ds-nav-row-h:\s*32px/);
  });

  it("does not center the page in a max-width column", () => {
    expect(rule(".shell-main")).not.toMatch(/max-width|margin/);
    expect(shellCss).not.toContain("--ds-layout-max");
  });
});
