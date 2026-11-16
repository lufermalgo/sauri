// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { copy } from "../copy/es";
import { SETTINGS_CATEGORIES, useRoute, type SettingsCategory } from "../router";
import type { SessionUser } from "../session-user";
import { THEME_STORAGE_KEY, initTheme } from "../theme";
import { PortalShell } from "./PortalShell";
import { SettingsView } from "./SettingsView";
import { SIDEBAR_STORAGE_KEY } from "./useSidebar";

const owner = { name: "Ana Maria Perez", email: "ana@example.test" };
const labels = copy.settings.categories;

function createLocalStorage(initial: Record<string, string> = {}): Storage {
  const values = new Map<string, string>(Object.entries(initial));
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
  return {
    get length() { return 0; },
    clear: fail, getItem: fail, key: fail, removeItem: fail, setItem: fail,
  };
}

let viewportWidth = 1440;
const mediaListeners = new Set<() => void>();

function stubViewport(width: number) {
  viewportWidth = width;
  vi.stubGlobal("matchMedia", (query: string) => ({
    get matches() { return viewportWidth <= Number(/max-width:\s*(\d+)px/.exec(query)?.[1] ?? Infinity); },
    media: query,
    addEventListener: (_type: string, listener: () => void) => mediaListeners.add(listener),
    removeEventListener: (_type: string, listener: () => void) => mediaListeners.delete(listener),
  }));
}

function Harness({ user = owner, onLogout = () => undefined }: { user?: SessionUser | null; onLogout?: () => void }) {
  const route = useRoute();
  return route.name === "settings" ? <SettingsView route={route} user={user} onLogout={onLogout} /> : null;
}

function open(category?: SettingsCategory) {
  window.history.replaceState({}, "", category ? `/settings/${labels[category].slug}` : "/settings");
}

const nav = () => screen.getByRole("navigation", { name: copy.settings.navLabel });

beforeEach(() => {
  mediaListeners.clear();
  stubViewport(1440);
  vi.stubGlobal("localStorage", createLocalStorage({ sauri_token: "synthetic-token" }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.documentElement.removeAttribute("data-theme");
  window.history.replaceState({}, "", "/");
});

describe("settings navigation", () => {
  it("lists the four categories and shows the account by default", () => {
    open();
    render(<Harness />);
    const links = within(nav()).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual(SETTINGS_CATEGORIES.map((name) => labels[name].label));
    expect(screen.getByRole("heading", { level: 1, name: copy.settings.title })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: labels.account.label })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: labels.account.label })).toHaveAttribute("aria-current", "page");
  });

  it.each(SETTINGS_CATEGORIES)("opens %s from its deep link and from the list without reloading", (category) => {
    open(category);
    render(<Harness />);
    expect(screen.getByRole("heading", { level: 2, name: labels[category].label })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: labels[category].label })).toHaveAttribute("aria-current", "page");

    const other = SETTINGS_CATEGORIES.find((name) => name !== category)!;
    fireEvent.click(screen.getByRole("link", { name: labels[other].label }));
    expect(window.location.pathname).toBe(`/settings/${labels[other].slug}`);
    expect(screen.getByRole("heading", { level: 2, name: labels[other].label })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 2, name: labels[category].label })).toBeNull();
  });

  it("leaves modified clicks on a category link to the browser", () => {
    open();
    render(<Harness />);
    let componentPrevented: boolean | null = null;
    const onWindowClick = (event: Event) => {
      componentPrevented = event.defaultPrevented;
      event.preventDefault(); // keeps jsdom from trying to navigate
    };
    window.addEventListener("click", onWindowClick);
    fireEvent.click(screen.getByRole("link", { name: labels.recording.label }), { ctrlKey: true });
    window.removeEventListener("click", onWindowClick);
    expect(componentPrevented).toBe(false);
    expect(window.location.pathname).toBe("/settings");
  });

  it("gives every category link a real, ASCII address", () => {
    open();
    render(<Harness />);
    for (const name of SETTINGS_CATEGORIES) {
      expect(screen.getByRole("link", { name: labels[name].label })).toHaveAttribute("href", `/settings/${labels[name].slug}`);
    }
  });
});

describe("settings on a small screen", () => {
  beforeEach(() => stubViewport(500));

  it("shows only the list first, then a category with a back button", () => {
    open();
    render(<Harness />);
    expect(within(nav()).getAllByRole("link")).toHaveLength(SETTINGS_CATEGORIES.length);
    expect(screen.queryByRole("heading", { level: 2 })).toBeNull();
    expect(screen.queryByRole("button", { name: copy.settings.backLabel })).toBeNull();

    fireEvent.click(screen.getByRole("link", { name: new RegExp(labels.appearance.label) }));
    expect(window.location.pathname).toBe(`/settings/${labels.appearance.slug}`);
    expect(screen.queryByRole("navigation", { name: copy.settings.navLabel })).toBeNull();
    const heading = screen.getByRole("heading", { level: 2, name: labels.appearance.label });
    expect(heading).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: copy.settings.backLabel }));
    expect(window.location.pathname).toBe("/settings");
    expect(screen.queryByRole("heading", { level: 2 })).toBeNull();
    expect(within(nav()).getAllByRole("link")).toHaveLength(SETTINGS_CATEGORIES.length);
  });

  it("opens a deep link straight on its category", () => {
    open("summaries");
    render(<Harness />);
    expect(screen.getByRole("heading", { level: 2, name: labels.summaries.label })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.settings.backLabel })).toBeInTheDocument();
  });
});

describe("account", () => {
  it("shows the name and email from the sign-in as read-only text and signs out", () => {
    const onLogout = vi.fn();
    open("account");
    render(<Harness onLogout={onLogout} />);
    expect(screen.getByText(owner.name)).toBeInTheDocument();
    expect(screen.getByText(owner.email)).toBeInTheDocument();
    expect(screen.getByText(copy.settings.account.note)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: copy.shell.logout }));
    expect(onLogout).toHaveBeenCalledTimes(1);
  });

  it("leads with the email when the token has no name, and falls back to a generic label", () => {
    open("account");
    const { unmount } = render(<Harness user={{ name: null, email: owner.email }} />);
    expect(document.querySelector(".settings-account-name")?.textContent).toBe(owner.email);
    expect(document.querySelector(".settings-account-email")).toBeNull();
    unmount();
    render(<Harness user={null} />);
    expect(document.querySelector(".settings-account-name")?.textContent).toBe(copy.settings.account.fallbackName);
    expect(document.querySelector(".ui-avatar svg")).toBeTruthy();
  });
});

describe("appearance: theme", () => {
  const radio = (name: string) => screen.getByRole("radio", { name });
  const themes = copy.settings.appearance.themes;

  it("offers system, light and dark as one labelled radio group, system first", () => {
    open("appearance");
    render(<Harness />);
    const group = screen.getByRole("group", { name: copy.settings.appearance.themeLabel });
    expect(within(group).getAllByRole("radio").map((item) => item.closest("label")?.textContent))
      .toEqual([themes.system, themes.light, themes.dark]);
    expect(radio(themes.system)).toBeChecked();
  });

  it("applies the choice at once, remembers it, and clears the override for system", () => {
    open("appearance");
    render(<Harness />);
    fireEvent.click(radio(themes.dark));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(radio(themes.dark)).toBeChecked();

    fireEvent.click(radio(themes.light));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");

    fireEvent.click(radio(themes.system));
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("system");
  });

  it("survives a reload: the stored choice is applied at start and shown selected", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    initTheme();
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    open("appearance");
    render(<Harness />);
    expect(radio(themes.dark)).toBeChecked();
  });

  it("works with blocked storage: it applies for this visit and nothing throws", () => {
    vi.stubGlobal("localStorage", blockedStorage());
    initTheme();
    open("appearance");
    render(<Harness />);
    expect(radio(themes.system)).toBeChecked();
    fireEvent.click(radio(themes.dark));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(radio(themes.dark)).toBeChecked();
  });
});

describe("appearance: side panel", () => {
  const sidebarSwitch = () => screen.getByRole("switch", { name: copy.settings.appearance.sidebarSwitch });

  it("reflects and changes the stored sidebar preference", () => {
    open("appearance");
    render(<Harness />);
    expect(sidebarSwitch()).toHaveAttribute("aria-checked", "false");
    fireEvent.click(sidebarSwitch());
    expect(localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("1");
    expect(sidebarSwitch()).toHaveAttribute("aria-checked", "true");
    fireEvent.click(sidebarSwitch());
    expect(localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("0");
    expect(sidebarSwitch()).toHaveAttribute("aria-checked", "false");
  });

  it("starts from the stored preference", () => {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, "1");
    open("appearance");
    render(<Harness />);
    expect(sidebarSwitch()).toHaveAttribute("aria-checked", "true");
  });

  it("collapses the live side panel without a reload and stays in sync with its toggle", () => {
    open("appearance");
    render(
      <PortalShell route={{ name: "settings", category: "appearance" }} user={owner} onLogout={vi.fn()}>
        <Harness />
      </PortalShell>,
    );
    const root = document.querySelector<HTMLElement>(".shell-root")!;
    expect(root.dataset.mode).toBe("full");
    fireEvent.click(sidebarSwitch());
    expect(root.dataset.mode).toBe("rail");

    fireEvent.click(screen.getByRole("button", { name: copy.shell.sidebar.toggle }));
    expect(root.dataset.mode).toBe("full");
    expect(sidebarSwitch()).toHaveAttribute("aria-checked", "false");
  });

  it("keeps the choice for this visit when storage is blocked", () => {
    vi.stubGlobal("localStorage", blockedStorage());
    open("appearance");
    render(<Harness />);
    fireEvent.click(sidebarSwitch());
    expect(sidebarSwitch()).toHaveAttribute("aria-checked", "true");
    fireEvent.click(sidebarSwitch());
    expect(sidebarSwitch()).toHaveAttribute("aria-checked", "false");
  });
});

describe("recording", () => {
  it("is informational: it points to the extension and has no controls", () => {
    open("recording");
    render(<Harness />);
    expect(screen.getByText(copy.settings.recording.body)).toBeInTheDocument();
    const detail = document.querySelector<HTMLElement>(".settings-detail")!;
    expect(within(detail).queryAllByRole("button")).toHaveLength(0);
    expect(within(detail).queryAllByRole("switch")).toHaveLength(0);
    expect(within(detail).queryAllByRole("textbox")).toHaveLength(0);
    expect(within(detail).queryAllByRole("radio")).toHaveLength(0);
  });
});

describe("settings inside the app shell", () => {
  it("keeps the shell's gear current while a category is open", async () => {
    open("summaries");
    vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200 })));
    await act(async () => {
      render(
        <PortalShell route={{ name: "settings", category: "summaries" }} user={owner} onLogout={vi.fn()}>
          <Harness />
        </PortalShell>,
      );
    });
    expect(screen.getByRole("link", { name: copy.shell.profile.settings })).toHaveAttribute("aria-current", "page");
    await waitFor(() => expect(screen.getByText(copy.settings.summaries.empty)).toBeInTheDocument());
  });
});
