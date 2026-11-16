// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { SETTINGS_CATEGORIES, SETTINGS_GROUPS, SETTINGS_SLUGS, useRoute, type SettingsCategory } from "../router";
import type { SessionUser } from "../session-user";
import { THEME_STORAGE_KEY, initTheme } from "../theme";
import { answerEnginesApi } from "./engineApiStub";
import { PortalShell } from "./PortalShell";
import { SettingsView } from "./SettingsView";
import { SIDEBAR_STORAGE_KEY } from "./useSidebar";
import { t } from "../i18n";

const owner = { name: "Ana Maria Perez", email: "ana@example.test" };

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
  window.history.replaceState({}, "", category ? `/settings/${SETTINGS_SLUGS[category]}` : "/settings");
}

function stubEngineApi() {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => answerEnginesApi(new URL(String(input)).pathname)!));
}

const nav = () => screen.getByRole("navigation", { name: t("settings:navLabel") });

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
  it("lists every category in group order and shows the account by default", () => {
    open();
    render(<Harness />);
    const links = within(nav()).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual(SETTINGS_CATEGORIES.map((name) => t(`settings:categories.${name}.label`)));
    expect(screen.getByRole("heading", { level: 1, name: t("settings:title") })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: t("settings:categories.account.label") })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: t("settings:categories.account.label") })).toHaveAttribute("aria-current", "page");
  });

  it.each(SETTINGS_CATEGORIES)("opens %s from its deep link and from the list without reloading", (category) => {
    open(category);
    render(<Harness />);
    expect(screen.getByRole("heading", { level: 2, name: t(`settings:categories.${category}.label`) })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: t(`settings:categories.${category}.label`) })).toHaveAttribute("aria-current", "page");

    const other = SETTINGS_CATEGORIES.find((name) => name !== category)!;
    fireEvent.click(screen.getByRole("link", { name: t(`settings:categories.${other}.label`) }));
    expect(window.location.pathname).toBe(`/settings/${SETTINGS_SLUGS[other]}`);
    expect(screen.getByRole("heading", { level: 2, name: t(`settings:categories.${other}.label`) })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 2, name: t(`settings:categories.${category}.label`) })).toBeNull();
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
    fireEvent.click(screen.getByRole("link", { name: t("settings:categories.summaries.label") }), { ctrlKey: true });
    window.removeEventListener("click", onWindowClick);
    expect(componentPrevented).toBe(false);
    expect(window.location.pathname).toBe("/settings");
  });

  it("gives every category link a real, ASCII address", () => {
    open();
    render(<Harness />);
    for (const name of SETTINGS_CATEGORIES) {
      expect(screen.getByRole("link", { name: t(`settings:categories.${name}.label`) })).toHaveAttribute("href", `/settings/${SETTINGS_SLUGS[name]}`);
    }
  });
});

describe("settings navigation groups", () => {
  it("names each group with a small label and lists its categories under it", () => {
    open();
    render(<Harness />);
    const groups = within(nav()).getAllByRole("group");
    expect(groups).toHaveLength(SETTINGS_GROUPS.length);
    SETTINGS_GROUPS.forEach((group, index) => {
      expect(groups[index]).toHaveAccessibleName(t(`settings:groups.${group.id}`));
      expect(within(groups[index]).getAllByRole("link").map((link) => link.textContent))
        .toEqual(group.categories.map((name) => t(`settings:categories.${name}.label`)));
    });
  });

  it("marks only the open category with aria-current", () => {
    open("transcription");
    render(<Harness />);
    const current = within(nav()).getAllByRole("link").filter((link) => link.getAttribute("aria-current") === "page");
    expect(current.map((link) => link.textContent)).toEqual([t("settings:categories.transcription.label")]);
  });

  it.each(["transcription", "speakers"] as const)(
    "shows the engine selector of %s instead of a placeholder",
    async (category) => {
      stubEngineApi();
      open(category);
      render(<Harness />);
      expect(screen.getByRole("heading", { level: 2, name: t(`settings:categories.${category}.label`) })).toBeInTheDocument();
      const detail = document.querySelector<HTMLElement>(".settings-detail")!;
      expect(await within(detail).findByLabelText(t("engines:process.engineLabel"))).toBeInTheDocument();
      expect(within(detail).getByText(/Hoy usa:/)).toBeInTheDocument(); // spanish-sample-data
    },
  );

  it("does not list or route the reserved chat category", () => {
    open();
    render(<Harness />);
    expect(within(nav()).queryByRole("link", { name: /chat/i })).toBeNull();
  });
});

describe("settings search", () => {
  const search = () => screen.getByRole("searchbox", { name: t("settings:search.label") });
  const shown = () => within(nav()).queryAllByRole("link").map((link) => link.textContent);
  const type = (value: string) => fireEvent.change(search(), { target: { value } });

  it("has a labelled field with a visible «Buscar» placeholder", () => {
    open();
    render(<Harness />);
    expect(search()).toHaveAttribute("placeholder", t("settings:search.placeholder"));
    expect(within(nav()).getByRole("searchbox")).toBe(search());
  });

  it.each([
    ["claves", ["engines"]],
    ["whisper", ["transcription"]],
    ["privacidad", ["engines", "transcription", "speakers"]],
    ["modelo", ["engines", "transcription", "speakers", "summaries"]],
  ] as const)("filters by keyword «%s»", (query, expected) => {
    open();
    render(<Harness />);
    type(query);
    expect(shown()).toEqual(expected.map((name) => t(`settings:categories.${name}.label`)));
  });

  it("ignores accents and case, and matches label and description", () => {
    open();
    render(<Harness />);
    type("TRANSCRIPCION"); // spanish-sample-data
    expect(shown()).toEqual([t("settings:categories.transcription.label")]);
    type("resumen");
    expect(shown()).toEqual([t("settings:categories.summaries.label")]);
    type("sesion");
    expect(shown()).toEqual([t("settings:categories.account.label")]);
    type("quien habla");
    expect(shown()).toEqual([t("settings:categories.speakers.label")]);
  });

  it("hides empty groups and announces the count politely", () => {
    open();
    render(<Harness />);
    type("claves");
    expect(within(nav()).getAllByRole("group")).toHaveLength(1);
    expect(within(nav()).getByRole("group")).toHaveAccessibleName(t("settings:groups.models"));
    expect(within(nav()).getByRole("status")).toHaveTextContent(t("settings:search.resultCount", { count: 1 }));
  });

  it("says «Sin resultados» and lists nothing when nothing matches", () => {
    open();
    render(<Harness />);
    type("zzzz");
    expect(shown()).toEqual([]);
    expect(within(nav()).queryAllByRole("group")).toHaveLength(0);
    expect(within(nav()).getByRole("status")).toHaveTextContent(t("settings:search.noResultsFor", { query: "zzzz" }));
    expect(within(nav()).getByRole("status").textContent).toMatch(/^Sin resultados/);
  });

  it("clears with Escape and with the clear button, keeping the focus in the field", () => {
    open();
    render(<Harness />);
    type("claves");
    fireEvent.keyDown(search(), { key: "Escape" });
    expect(search()).toHaveValue("");
    expect(shown()).toHaveLength(SETTINGS_CATEGORIES.length);

    type("whisper");
    fireEvent.click(screen.getByRole("button", { name: t("settings:search.clear") }));
    expect(search()).toHaveValue("");
    expect(search()).toHaveFocus();
    expect(screen.queryByRole("button", { name: t("settings:search.clear") })).toBeNull();
  });

  it("keeps the open category selected while it still matches, and the page unchanged when it does not", () => {
    open("summaries");
    render(<Harness />);
    type("resumen");
    expect(screen.getByRole("link", { name: t("settings:categories.summaries.label") })).toHaveAttribute("aria-current", "page");
    type("whisper");
    expect(window.location.pathname).toBe(`/settings/${SETTINGS_SLUGS.summaries}`);
    expect(screen.getByRole("heading", { level: 2, name: t("settings:categories.summaries.label") })).toBeInTheDocument();
  });

  it("opens the first result with Enter", () => {
    open();
    render(<Harness />);
    type("whisper");
    fireEvent.keyDown(search(), { key: "Enter" });
    expect(window.location.pathname).toBe(`/settings/${SETTINGS_SLUGS.transcription}`);
    expect(screen.getByRole("heading", { level: 2, name: t("settings:categories.transcription.label") })).toBeInTheDocument();
  });

  it("moves between the field and the rows with the arrow keys", () => {
    open();
    render(<Harness />);
    search().focus();
    fireEvent.keyDown(search(), { key: "ArrowDown" });
    expect(screen.getByRole("link", { name: t("settings:categories.account.label") })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(screen.getByRole("link", { name: t("settings:categories.appearance.label") })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
    fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
    expect(search()).toHaveFocus();
  });

  it("filters the small-screen list too, and keeps the filter when coming back", () => {
    stubViewport(500);
    open();
    render(<Harness />);
    type("hablantes"); // spanish-sample-data
    expect(shown()).toHaveLength(1);
    fireEvent.click(screen.getByRole("link", { name: new RegExp(t("settings:categories.speakers.label")) }));
    expect(screen.queryByRole("searchbox")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: t("settings:backLabel") }));
    expect(search()).toHaveValue("hablantes"); // spanish-sample-data
    expect(shown()).toHaveLength(1);
  });
});

describe("settings navigation sizing", () => {
  const css = readFileSync(join(__dirname, "../styles/settings.css"), "utf8");
  const tokens = readFileSync(join(__dirname, "../design/tokens.css"), "utf8");

  it("sizes rows and the search field from the touch-aware tokens: 32px on desktop, 44px on touch", () => {
    expect(/\.settings-nav-link\s*\{[^}]*min-height:\s*var\(--ds-nav-row-h\)/.test(css)).toBe(true);
    expect(/\.settings-search\s*\{[^}]*min-height:\s*var\(--ds-control-h-md\)/.test(css)).toBe(true);
    expect(tokens).toMatch(/--ds-nav-row-h:\s*32px/);
    const coarse = /@media \(pointer: coarse\)\s*\{([\s\S]*?)\n\}/.exec(tokens)?.[1] ?? "";
    expect(coarse).toMatch(/--ds-nav-row-h:\s*44px/);
    expect(coarse).toMatch(/--ds-control-h-md:\s*44px/);
    expect(coarse).toMatch(/--ds-control-h-lg:\s*44px/);
  });
});

describe("settings on a small screen", () => {
  beforeEach(() => stubViewport(500));

  it("shows only the list first, then a category with a back button", () => {
    open();
    render(<Harness />);
    expect(within(nav()).getAllByRole("link")).toHaveLength(SETTINGS_CATEGORIES.length);
    expect(screen.queryByRole("heading", { level: 2 })).toBeNull();
    expect(screen.queryByRole("button", { name: t("settings:backLabel") })).toBeNull();

    fireEvent.click(screen.getByRole("link", { name: new RegExp(t("settings:categories.appearance.label")) }));
    expect(window.location.pathname).toBe(`/settings/${SETTINGS_SLUGS.appearance}`);
    expect(screen.queryByRole("navigation", { name: t("settings:navLabel") })).toBeNull();
    const heading = screen.getByRole("heading", { level: 2, name: t("settings:categories.appearance.label") });
    expect(heading).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: t("settings:backLabel") }));
    expect(window.location.pathname).toBe("/settings");
    expect(screen.queryByRole("heading", { level: 2 })).toBeNull();
    expect(within(nav()).getAllByRole("link")).toHaveLength(SETTINGS_CATEGORIES.length);
  });

  it("opens a deep link straight on its category", () => {
    open("summaries");
    render(<Harness />);
    expect(screen.getByRole("heading", { level: 2, name: t("settings:categories.summaries.label") })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: t("settings:backLabel") })).toBeInTheDocument();
  });
});

describe("account", () => {
  it("shows the name and email from the sign-in as read-only text and signs out", () => {
    const onLogout = vi.fn();
    open("account");
    render(<Harness onLogout={onLogout} />);
    expect(screen.getByText(owner.name)).toBeInTheDocument();
    expect(screen.getByText(owner.email)).toBeInTheDocument();
    expect(screen.getByText(t("settings:account.note"))).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: t("shell:logout") }));
    expect(onLogout).toHaveBeenCalledTimes(1);
  });

  it("leads with the email when the token has no name, and falls back to a generic label", () => {
    open("account");
    const { unmount } = render(<Harness user={{ name: null, email: owner.email }} />);
    expect(document.querySelector(".settings-account-name")?.textContent).toBe(owner.email);
    expect(document.querySelector(".settings-account-email")).toBeNull();
    unmount();
    render(<Harness user={null} />);
    expect(document.querySelector(".settings-account-name")?.textContent).toBe(t("settings:account.fallbackName"));
    expect(document.querySelector(".ui-avatar svg")).toBeTruthy();
  });
});

describe("appearance: theme", () => {
  const radio = (name: string) => screen.getByRole("radio", { name });

  it("offers system, light and dark as one labelled radio group, system first", () => {
    open("appearance");
    render(<Harness />);
    const group = screen.getByRole("group", { name: t("settings:appearance.themeLabel") });
    expect(within(group).getAllByRole("radio").map((item) => item.closest("label")?.textContent))
      .toEqual([t("settings:appearance.themes.system"), t("settings:appearance.themes.light"), t("settings:appearance.themes.dark")]);
    expect(radio(t("settings:appearance.themes.system"))).toBeChecked();
  });

  it("applies the choice at once, remembers it, and clears the override for system", () => {
    open("appearance");
    render(<Harness />);
    fireEvent.click(radio(t("settings:appearance.themes.dark")));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(radio(t("settings:appearance.themes.dark"))).toBeChecked();

    fireEvent.click(radio(t("settings:appearance.themes.light")));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");

    fireEvent.click(radio(t("settings:appearance.themes.system")));
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("system");
  });

  it("survives a reload: the stored choice is applied at start and shown selected", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    initTheme();
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    open("appearance");
    render(<Harness />);
    expect(radio(t("settings:appearance.themes.dark"))).toBeChecked();
  });

  it("works with blocked storage: it applies for this visit and nothing throws", () => {
    vi.stubGlobal("localStorage", blockedStorage());
    initTheme();
    open("appearance");
    render(<Harness />);
    expect(radio(t("settings:appearance.themes.system"))).toBeChecked();
    fireEvent.click(radio(t("settings:appearance.themes.dark")));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(radio(t("settings:appearance.themes.dark"))).toBeChecked();
  });
});

describe("appearance: side panel", () => {
  const sidebarSwitch = () => screen.getByRole("switch", { name: t("settings:appearance.sidebarSwitch") });

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

    fireEvent.click(screen.getByRole("button", { name: t("shell:sidebar.toggle") }));
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
    expect(screen.getByRole("button", { name: t("shell:profile.settings") })).toHaveAttribute("aria-current", "page");
    await waitFor(() => expect(screen.getByText(t("settings:summaries.empty"))).toBeInTheDocument());
  });
});
